"""Privacy guard — unit tests for PII detection, severity, and redaction."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import pytest

from app.services.privacy.guard import (
    Finding,
    PrivacyCheckResult,
    _validate_israeli_id,
    check_text,
)


# ── Email ─────────────────────────────────────────────────────────────────────

def test_email_detected():
    result = check_text("Contact me at user@example.com for details.")
    assert any(f.type == "email" for f in result.findings)


def test_email_is_high_severity():
    result = check_text("admin@gov.il")
    email_findings = [f for f in result.findings if f.type == "email"]
    assert email_findings
    assert all(f.severity == "high" for f in email_findings)


def test_email_blocks_external_call():
    result = check_text("Send to hr@ministry.gov.il please.")
    assert result.allowed is False
    assert result.reason is not None


# ── Phone ─────────────────────────────────────────────────────────────────────

def test_phone_detected():
    result = check_text("Call me at 050-1234567 tomorrow.")
    assert any(f.type == "phone" for f in result.findings)


def test_phone_is_high_severity():
    result = check_text("My number is 052-9876543.")
    phone_findings = [f for f in result.findings if f.type == "phone"]
    assert phone_findings
    assert all(f.severity == "high" for f in phone_findings)


def test_phone_blocks_external_call():
    result = check_text("My number is 052-9876543.")
    assert result.allowed is False


# ── Israeli ID ────────────────────────────────────────────────────────────────

def test_valid_israeli_id_checksum():
    # 123456782: sum = 1+4+3+8+5+3+7+7+2 = 40 → divisible by 10 ✓
    assert _validate_israeli_id("123456782") is True


def test_invalid_nine_digits_fail_checksum():
    # 123456789: sum = 1+4+3+8+5+3+7+7+9 = 47 → not divisible by 10
    assert _validate_israeli_id("123456789") is False


def test_israeli_id_detected():
    result = check_text("My ID is 123456782.")
    assert any(f.type == "israeli_id" for f in result.findings)


def test_israeli_id_blocks_external_call():
    result = check_text("ת.ז. 123456782")
    assert result.allowed is False


def test_nine_digits_without_valid_checksum_not_flagged_as_id():
    result = check_text("Reference number: 123456789")
    id_findings = [f for f in result.findings if f.type == "israeli_id"]
    assert not id_findings


# ── Employee number ───────────────────────────────────────────────────────────

def test_employee_number_detected():
    result = check_text('מ"א 54321 חוזר לעבודה')
    assert any(f.type == "employee_number" for f in result.findings)


def test_employee_number_is_medium_severity():
    result = check_text('מ"א 54321')
    emp_findings = [f for f in result.findings if f.type == "employee_number"]
    assert emp_findings
    assert all(f.severity == "medium" for f in emp_findings)


def test_employee_number_alone_does_not_block():
    result = check_text('מ"א 54321')
    assert all(f.severity != "high" for f in result.findings)
    assert result.allowed is True


# ── Sensitive context ─────────────────────────────────────────────────────────

def test_sensitive_health_context_detected():
    result = check_text("העובד נמצא בחופשת לידה.")
    assert any(f.type == "sensitive_context" for f in result.findings)


def test_sensitive_discipline_context_detected():
    result = check_text("בירור משמעתי יתקיים מחר.")
    assert any(f.type == "sensitive_context" for f in result.findings)


def test_sensitive_context_is_medium_severity():
    result = check_text("העובד אושפז.")
    ctx = [f for f in result.findings if f.type == "sensitive_context"]
    assert ctx
    assert all(f.severity == "medium" for f in ctx)


def test_sensitive_context_alone_does_not_block():
    result = check_text("מחלה קשה")
    high = [f for f in result.findings if f.severity == "high"]
    if not high:
        assert result.allowed is True


# ── Safe text ─────────────────────────────────────────────────────────────────

def test_safe_general_hr_question_allowed():
    result = check_text("מה הם כללי חופשה שנתית לעובדי מדינה?")
    assert result.allowed is True
    assert result.findings == []


def test_empty_text_allowed():
    result = check_text("")
    assert result.allowed is True
    assert result.findings == []
    assert result.redacted_text is None


# ── Redaction ─────────────────────────────────────────────────────────────────

def test_redaction_removes_email():
    result = check_text("Email: admin@example.com")
    assert result.redacted_text is not None
    assert "admin@example.com" not in result.redacted_text
    assert "[REDACTED:email]" in result.redacted_text


def test_redaction_removes_phone():
    result = check_text("Phone: 050-1234567")
    assert result.redacted_text is not None
    assert "050-1234567" not in result.redacted_text
    assert "[REDACTED:phone]" in result.redacted_text


def test_no_redaction_when_no_findings():
    result = check_text("What is the sick leave policy?")
    assert result.redacted_text is None


# ── Severity logic ────────────────────────────────────────────────────────────

def test_high_severity_sets_allowed_false():
    result = check_text("My phone: 053-1234567")
    assert result.allowed is False


def test_medium_severity_alone_does_not_set_allowed_false():
    result = check_text("מחלה")
    high_findings = [f for f in result.findings if f.severity == "high"]
    if not high_findings:
        assert result.allowed is True
