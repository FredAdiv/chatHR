"""Tests verifying chat retrieval uses only the active index version.

Verifies:
- Normal chat answers only retrieve from active index.
- Draft/processed/approved but non-active index versions are excluded.
- No active index returns a safe 503 response.
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user_with_roles(*role_names):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.user_roles = [SimpleNamespace(role=SimpleNamespace(name=r)) for r in role_names]
    return user


def _auth(roles):
    u = _user_with_roles(*roles)
    def _dep():
        return u
    return _dep


def _make_conversation(user_id, context_type="government_ministries"):
    conv = MagicMock()
    conv.id = uuid.uuid4()
    conv.user_id = user_id
    conv.context_type = context_type
    conv.title = None
    conv.created_at = datetime.now(timezone.utc)
    return conv


def _make_iv(status="active"):
    iv = MagicMock()
    iv.id = uuid.uuid4()
    iv.status = status
    iv.version_label = f"test-v-{str(iv.id)[:8]}"
    return iv


def _db_mock_with_active_iv(conv, active_iv):
    """DB mock that returns an active index version."""
    async def mock_execute(stmt):
        result = MagicMock()
        # First call: get conversation; second call: get active index version
        result.scalar_one_or_none.return_value = active_iv
        result.scalars.return_value.all.return_value = []
        return result

    async def mock_get(model_class, pk):
        from app.db.models.conversation import Conversation
        if model_class is Conversation:
            return conv
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def _dep():
        yield mock_db
    return _dep


def _db_mock_no_active_iv(conv):
    """DB mock that returns no active index version."""
    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        call_count[0] += 1
        # conversation lookup returns conv, active IV lookup returns None
        if call_count[0] == 1:
            result.scalar_one_or_none.return_value = conv
        else:
            result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.execute = mock_execute

    async def _dep():
        yield mock_db
    return _dep


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_no_active_index_returns_503():
    """When no active index exists, chat must return 503 (not hallucinate)."""
    user = _user_with_roles("chat_user")
    conv = _make_conversation(user.id)

    def _dep():
        return user

    db_dep = _db_mock_no_active_iv(conv)

    app.dependency_overrides[get_current_active_user] = _dep
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.services.privacy.guard.check_text", return_value=MagicMock(allowed=True, findings=[])),
            patch("app.services.guardrails.input_guard.check_user_input", return_value=MagicMock(allowed=True)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "מה הכללים לגבי חופשת מחלה?"},
                )
        assert r.status_code == 503
        body = r.json()
        assert "active" in body.get("detail", "").lower() or "index" in body.get("detail", "").lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chat_explicit_non_active_index_version_returns_422():
    """When a non-active index_version_id is explicitly requested, chat must return 422."""
    user = _user_with_roles("chat_user")
    conv = _make_conversation(user.id)
    draft_iv = _make_iv(status="draft")

    def _dep():
        return user

    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        call_count[0] += 1
        if call_count[0] == 1:
            # conversation lookup
            result.scalar_one_or_none.return_value = conv
        else:
            # explicit index version lookup with status='active' filter → returns None
            result.scalar_one_or_none.return_value = None
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _dep
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.services.privacy.guard.check_text", return_value=MagicMock(allowed=True, findings=[])),
            patch("app.services.guardrails.input_guard.check_user_input", return_value=MagicMock(allowed=True)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה", "index_version_id": str(draft_iv.id)},
                )
        # The endpoint requires the explicitly-requested index to have status='active'
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chat_uses_active_index_only():
    """Chat must use the active index, not any draft or quality_check_failed version."""
    user = _user_with_roles("chat_user")
    conv = _make_conversation(user.id)
    active_iv = _make_iv(status="active")

    def _dep():
        return user

    call_count = [0]

    async def mock_execute(stmt):
        result = MagicMock()
        call_count[0] += 1
        # Return conv on first call (conversation lookup), then active_iv (index lookup)
        result.scalar_one_or_none.return_value = active_iv if call_count[0] > 1 else conv
        result.scalars.return_value.all.return_value = []
        return result

    async def mock_refresh(obj):
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(timezone.utc)
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "role") and obj.role is None:
            obj.role = "assistant"
        if hasattr(obj, "content") and obj.content is None:
            obj.content = "אין מידע זמין"
        if hasattr(obj, "message_id") and obj.message_id is None:
            obj.message_id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = mock_refresh

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _dep
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.services.privacy.guard.check_text", return_value=MagicMock(allowed=True, findings=[])),
            patch("app.services.guardrails.input_guard.check_user_input", return_value=MagicMock(allowed=True)),
            patch("app.api.chat.retrieve_chunks", AsyncMock(return_value=[])),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(
                    f"/chat/conversations/{conv.id}/messages",
                    json={"content": "שאלה על מדיניות"},
                )
        # With no chunks retrieved the endpoint returns a safe no-sources response — not 503 or 4xx
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
