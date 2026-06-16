# Privacy Guard — Phase 10

## Overview

The privacy guard inspects text before any external model call. It is the first layer of protection ensuring no personally identifiable information (PII) is sent to external AI providers.

**Module:** `apps/api/app/services/privacy/guard.py`  
**Entry point:** `check_text(text: str) -> PrivacyCheckResult`

## Detection Capabilities

| Finding Type | Pattern | Severity | Blocks Call |
|---|---|---|---|
| `email` | Standard email addresses | high | ✅ Yes |
| `phone` | Israeli mobile (05X), landline (0X), international (+972) | high | ✅ Yes |
| `israeli_id` | 9-digit sequences passing the Israeli ID checksum | high | ✅ Yes |
| `employee_number` | מ"א + digits, employee id patterns | medium | ❌ No |
| `sensitive_context` | Health/discipline keywords (Hebrew) | medium | ❌ No |

### Severity Rules

- **High severity** (`email`, `phone`, `israeli_id`): any high-severity finding causes `allowed=False` and blocks the external model call.
- **Medium severity** (`employee_number`, `sensitive_context`): findings are recorded but do not block. They appear in `PrivacyCheckResult.findings`.

## Data Model

```python
@dataclass
class Finding:
    type: FindingType         # email | phone | israeli_id | employee_number | sensitive_context
    severity: Severity        # high | medium
    span_start: int | None    # character position in original text
    span_end: int | None
    matched_text: str | None  # internal only — never exposed in public API responses

@dataclass
class PrivacyCheckResult:
    allowed: bool             # False if any high-severity finding
    findings: list[Finding]
    redacted_text: str | None  # original text with matches replaced by [REDACTED:type]
    reason: str | None         # human-readable block reason (high severity only)
```

## Redaction

When findings exist, `redacted_text` is returned with matched spans replaced:
- `admin@gov.il` → `[REDACTED:email]`
- `050-1234567` → `[REDACTED:phone]`
- `123456782` → `[REDACTED:israeli_id]`
- `מ"א 54321` → `[REDACTED:employee_number]`
- `אשפוז` → `[REDACTED:sensitive_context]`

`redacted_text` is safe to use in debug logs. The original text must never be logged.

## Israeli ID Detection

Uses the standard Israeli national ID checksum algorithm:
- For each digit at position i (0-indexed): multiply by `1` if even position, `2` if odd.
- If result > 9, subtract 9.
- Sum must be divisible by 10.

Only 9-digit sequences passing this checksum are flagged as `israeli_id`.

## Sensitive Context Keywords (Hebrew)

Health terms: מחלה, חולה, ניתוח, אשפוז, אושפז, טיפול רפואי, בעיה רפואית, מצב רפואי, נכות, הריון, לידה  
Discipline terms: משמעת, בירור משמעתי, ועדת משמעת, פיטורים, השעיה, אזהרה כתובה, בירור אישי, חקירה פנימית

## Limitations (MVP)

- **Pattern-matching only** — no semantic understanding. A phone number in a document title ("חוקי 050") would be flagged.
- **Hebrew keywords only** for sensitive context — English equivalents are not detected.
- **Keyword-level detection** for sensitive context — not combined with identifiers as originally described. Any occurrence of the keyword is flagged.
- **No ML-based NER** — false positives and false negatives are expected.
- **9-digit sequences** with valid checksums will be flagged even if they're not IDs (e.g., product codes).
- Detection is synchronous and single-threaded — no batching.

## Constraints

- Never calls external services — all detection is local and deterministic.
- `matched_text` in `Finding` is internal; never exposed in public API responses.
- `redacted_text` is safe for logs but original input text must never be logged.
- Privacy guard must run before every external model call (enforced by the LLM Gateway).
