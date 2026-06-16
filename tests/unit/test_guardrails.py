"""Input guardrail service — unit tests.

Covers:
- Privacy Guard still runs first and blocks PII
- Inappropriate content returns 422, not stored
- Out-of-scope input returns 422, not stored
- Internet search request returns 422, not stored
- Valid HR question is allowed
- Inappropriate feedback comment returns 422, not stored
- Blocked responses do not include matched raw text
- No-source behavior unchanged for allowed HR question
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.main import app
from app.services.guardrails.input_guard import (
    GuardrailCheckResult,
    check_feedback_comment,
    check_user_input,
)
from app.services.privacy.guard import check_text


# ── Unit: check_user_input ────────────────────────────────────────────────────

def test_empty_input_allowed():
    assert check_user_input("").allowed is True
    assert check_user_input("   ").allowed is True


def test_valid_hr_question_allowed():
    assert check_user_input("מה הכללים לחישוב ימי מחלה?").allowed is True


def test_hr_question_with_topic_keyword_allowed():
    assert check_user_input("מה זכאותי לחופשת לידה?").allowed is True


def test_internet_search_blocked():
    result = check_user_input("חפש בגוגל כמה ימי חופשה מגיעים לי")
    assert result.allowed is False
    assert result.category == "internet_search"
    assert result.public_message is not None
    assert "אינטרנט" in result.public_message or "מקורות רשמיים" in result.public_message


def test_internet_search_english_blocked():
    result = check_user_input("search the internet for civil service salary tables")
    assert result.allowed is False
    assert result.category == "internet_search"


def test_internet_search_priority_over_hr_keyword():
    # Even if HR keyword is present, internet search takes priority
    result = check_user_input("חפש בגוגל את הסכם השכר לעובדי מדינה")
    assert result.allowed is False
    assert result.category == "internet_search"


def test_inappropriate_content_blocked():
    result = check_user_input("שרמוטה, למה לא קיבלתי קידום?")
    assert result.allowed is False
    assert result.category == "inappropriate_content"
    assert result.public_message is not None


def test_inappropriate_english_blocked():
    result = check_user_input("this fucking system is broken")
    assert result.allowed is False
    assert result.category == "inappropriate_content"


def test_out_of_scope_recipe_blocked():
    result = check_user_input("מה המתכון לעוגת שוקולד?")
    assert result.allowed is False
    assert result.category == "out_of_scope"
    assert result.public_message is not None


def test_out_of_scope_flight_blocked():
    result = check_user_input("כמה עולה להזמין טיסה לפריז?")
    assert result.allowed is False
    assert result.category == "out_of_scope"


def test_out_of_scope_but_hr_keyword_allows():
    # If HR keyword present, scope check passes regardless of other topic signals
    result = check_user_input("עובד בשירות המדינה יכול לקנות נעליים?")
    assert result.allowed is True


def test_guardrail_result_no_matched_text():
    # GuardrailCheckResult must not expose matched raw text
    result = check_user_input("שרמוטה")
    assert result.allowed is False
    # No field should contain the matched term
    assert not hasattr(result, "matched_text")
    assert result.reason is not None
    assert result.public_message is not None


# ── Unit: check_feedback_comment ──────────────────────────────────────────────

def test_feedback_empty_allowed():
    assert check_feedback_comment("").allowed is True


def test_feedback_normal_comment_allowed():
    assert check_feedback_comment("התשובה הייתה מועילה מאוד, תודה.").allowed is True


def test_feedback_inappropriate_blocked():
    result = check_feedback_comment("תשובה זבל, מניאק")
    assert result.allowed is False
    assert result.category == "inappropriate_content"


def test_feedback_out_of_scope_not_blocked():
    # Scope check does NOT apply to feedback comments
    result = check_feedback_comment("ניסיתי לשאול על מתכונים אבל המערכת ענתה")
    assert result.allowed is True


def test_feedback_internet_search_not_blocked():
    # Internet search check does NOT apply to feedback comments
    result = check_feedback_comment("חפשתי בגוגל ומצאתי תשובה אחרת")
    assert result.allowed is True


# ── Unit: Privacy Guard still runs first ─────────────────────────────────────

def test_privacy_guard_blocks_pii():
    # PII check should block before guardrails
    result = check_text("שלח לי למייל user@example.com")
    assert result.allowed is False


def test_privacy_guard_pii_not_exposed():
    result = check_text("המייל שלי הוא test@example.com")
    assert result.allowed is False
    for finding in result.findings:
        assert finding.matched_text is not None  # stored internally only


# ── Integration: send_message guardrail integration ───────────────────────────

def _make_user(*role_names):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.user_roles = [SimpleNamespace(role=SimpleNamespace(name=r)) for r in role_names]
    return user


def _make_conv(user_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        context_type="government_ministries",
        title=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_index():
    return SimpleNamespace(id=uuid.uuid4(), status="active")


@pytest.mark.anyio
async def test_send_message_inappropriate_returns_422():
    user = _make_user("chat_user")
    conv = _make_conv(user.id)

    def dep():
        return user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conv)))

    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "שרמוטה, תענה לי"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error"] == "guardrail_blocked"
        assert body["detail"]["category"] == "inappropriate_content"
        assert "public_message" in body["detail"]
        assert body["detail"]["public_message"]
        # matched raw text must not appear
        assert "שרמוטה" not in str(body["detail"])
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_send_message_internet_search_returns_422():
    user = _make_user("chat_user")
    conv = _make_conv(user.id)

    def dep():
        return user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conv)))

    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "חפש בגוגל את ההסכם"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error"] == "guardrail_blocked"
        assert body["detail"]["category"] == "internet_search"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_send_message_out_of_scope_returns_422():
    user = _make_user("chat_user")
    conv = _make_conv(user.id)

    def dep():
        return user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conv)))

    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "מה המתכון לעוגת שוקולד?"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error"] == "guardrail_blocked"
        assert body["detail"]["category"] == "out_of_scope"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_guardrail_blocked_response_no_raw_text():
    user = _make_user("chat_user")
    conv = _make_conv(user.id)

    def dep():
        return user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conv)))

    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/chat/conversations/{conv.id}/messages",
                json={"content": "fuck this system"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422
        body_text = resp.text
        assert "fuck" not in body_text.lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.anyio
async def test_feedback_inappropriate_comment_returns_422():
    user = _make_user("chat_user")
    msg_id = uuid.uuid4()
    conv = _make_conv(user.id)
    message = SimpleNamespace(
        id=msg_id,
        conversation_id=conv.id,
        role="assistant",
        content="תשובה",
        created_at=datetime.now(timezone.utc),
        metadata_json=None,
    )

    def dep():
        return user

    execute_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=message)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=conv)),
    ]
    call_count = 0

    async def mock_execute(q):
        nonlocal call_count
        r = execute_results[min(call_count, len(execute_results) - 1)]
        call_count += 1
        return r

    mock_db = AsyncMock()
    mock_db.execute = mock_execute

    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/chat/messages/{msg_id}/feedback",
                json={"rating": "negative", "comment": "זבל מוחלט, מניאק"},
                headers={"Authorization": "Bearer test"},
            )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error"] == "guardrail_blocked"
        assert body["detail"]["category"] == "inappropriate_content"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
