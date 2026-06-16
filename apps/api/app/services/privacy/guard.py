"""Privacy guard — detect PII and sensitive content before external model calls.

MVP detection (regex-based, deterministic, no external calls):
  high severity  → email, phone (Israeli), Israeli national ID
  medium severity → employee numbers, sensitive health/discipline keywords

If any high-severity finding exists the external call is blocked.
Medium-severity findings are flagged but do not block.

Limitations:
- Pattern-matching only; no semantic understanding.
- Hebrew-only for sensitive context keywords.
- Israeli ID detection uses the standard digit-sum checksum.
- False positives possible on 9-digit sequences with valid checksums.
- Sensitive context is keyword-level, not combined-identifier level.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FindingType = Literal["email", "phone", "israeli_id", "employee_number", "sensitive_context"]
Severity = Literal["low", "medium", "high"]


# ── Patterns ──────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b')

# Israeli mobile (05X-XXXXXXX), landline (0X-XXXXXXX), international (+972...)
_PHONE_RE = re.compile(
    r'(?:'
    r'(?:\+972|00972)[\s\-]?(?:0)?[1-9]\d?[\s\-]?\d{3,4}[\s\-]?\d{4}'
    r'|0(?:5[0-9]|[2-9]\d?)[\s\-]?\d{3,4}[\s\-]?\d{4}'
    r')'
)

# 9-digit sequence (candidate for Israeli national ID — validated by checksum)
_NINE_DIGITS_RE = re.compile(r'(?<!\d)(\d{9})(?!\d)')

# Employee number patterns: מ"א / מ״א + digits, employee id forms
_EMPLOYEE_NUM_RE = re.compile(
    r'(?:'
    r'מ[\"״”″"]א\s*:?\s*\d+'
    r'|מספר\s+(?:עובד|אישי)\s*:?\s*\d+'
    r'|employee\s*(?:id|#|no\.?|number)?\s*:?\s*\d+'
    r')',
    re.IGNORECASE,
)

# Sensitive health and discipline keywords (Hebrew)
_SENSITIVE_CONTEXT_RE = re.compile(
    r'(?:'
    r'מחל[הי]|חולה|חולי|ניתוח|אשפוז|[מ]?אושפז[ה]?|טיפול\s+רפואי|בעיה\s+רפואית|מצב\s+רפואי'
    r'|נכות|נכה|הריון|בהריון|לידה|חופשת\s+לידה'
    r'|משמעת|בירור\s+משמעתי|ועדת\s+משמעת|פיטורים|פיטורין|השעיה'
    r'|אזהרה\s+כתובה|בירור\s+אישי|חקירה\s+פנימית'
    r')',
    re.IGNORECASE,
)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Finding:
    type: FindingType
    severity: Severity
    span_start: int | None = None
    span_end: int | None = None
    matched_text: str | None = None  # internal only — never expose in public API responses


@dataclass
class PrivacyCheckResult:
    allowed: bool
    findings: list[Finding]
    redacted_text: str | None = None
    reason: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_israeli_id(digits: str) -> bool:
    """Verify 9-digit string against the Israeli national ID checksum algorithm."""
    total = 0
    for i, d in enumerate(digits):
        n = int(d) * ((i % 2) + 1)
        if n > 9:
            n -= 9
        total += n
    return total % 10 == 0


def _build_redacted(text: str, replacements: list[tuple[int, int, str]]) -> str:
    """Replace matched spans from right to left to preserve earlier span positions."""
    parts = list(text)
    for start, end, label in sorted(replacements, key=lambda x: x[0], reverse=True):
        parts[start:end] = list(label)
    return "".join(parts)


# ── Main entry point ──────────────────────────────────────────────────────────

def check_text(text: str) -> PrivacyCheckResult:
    """
    Inspect text for PII and sensitive content before any external model call.

    Returns a PrivacyCheckResult with:
      - allowed=False if any high-severity finding exists
      - redacted_text replacing all matched spans with [REDACTED:type] labels
      - findings list (matched_text populated internally; not for public exposure)

    Does not call external services. All detection is deterministic.
    """
    if not text:
        return PrivacyCheckResult(allowed=True, findings=[], redacted_text=None, reason=None)

    findings: list[Finding] = []
    replacements: list[tuple[int, int, str]] = []

    # Email → high severity
    for m in _EMAIL_RE.finditer(text):
        findings.append(Finding("email", "high", m.start(), m.end(), m.group()))
        replacements.append((m.start(), m.end(), "[REDACTED:email]"))

    # Phone → high severity
    for m in _PHONE_RE.finditer(text):
        findings.append(Finding("phone", "high", m.start(), m.end(), m.group()))
        replacements.append((m.start(), m.end(), "[REDACTED:phone]"))

    # Israeli national ID (9 digits passing checksum) → high severity
    for m in _NINE_DIGITS_RE.finditer(text):
        if _validate_israeli_id(m.group(1)):
            findings.append(Finding("israeli_id", "high", m.start(), m.end(), m.group()))
            replacements.append((m.start(), m.end(), "[REDACTED:israeli_id]"))

    # Employee number → medium severity
    for m in _EMPLOYEE_NUM_RE.finditer(text):
        findings.append(Finding("employee_number", "medium", m.start(), m.end(), m.group()))
        replacements.append((m.start(), m.end(), "[REDACTED:employee_number]"))

    # Sensitive context keywords → medium severity
    for m in _SENSITIVE_CONTEXT_RE.finditer(text):
        findings.append(Finding("sensitive_context", "medium", m.start(), m.end(), m.group()))
        replacements.append((m.start(), m.end(), "[REDACTED:sensitive_context]"))

    has_high = any(f.severity == "high" for f in findings)
    redacted = _build_redacted(text, replacements) if replacements else None

    return PrivacyCheckResult(
        allowed=not has_high,
        findings=findings,
        redacted_text=redacted,
        reason="High-severity PII detected — external model call blocked." if has_high else None,
    )
