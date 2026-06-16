"""Part B: FAQ management API tests — authorization and behavior."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.faq_item import FaqItem
from app.db.session import get_db
from app.main import app


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


def _db_for_create():
    """Mock DB for POST /admin/faq — handles add, flush, audit add+flush, commit."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_get(item):
    """Mock DB for routes that call db.get(FaqItem, id)."""
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=item)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_list(items=None):
    """Mock DB for GET /admin/faq list."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = items or []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


def _faq_item(status="draft", version=1):
    """Build a realistic FaqItem mock."""
    now = datetime.now(timezone.utc)
    item = MagicMock(spec=FaqItem)
    item.id = uuid.uuid4()
    item.question = "Can I transfer to another ministry?"
    item.answer = "Yes, subject to approval."
    item.topic = "mobility"
    item.context_type = "government_ministries"
    item.applicable_population = None
    item.official_source_links = []
    item.status = status
    item.approved_by_user_id = None
    item.approved_at = None
    item.content_version = version
    item.created_at = now
    item.updated_at = now
    return item


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_faq_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/faq")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_faq_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/faq")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_faq_user_admin_alone_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/faq", json={"question": "Q?", "answer": "A."})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Create FAQ ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_faq_manager_can_create_draft():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/faq", json={"question": "Q?", "answer": "A."})
        assert r.status_code == 201
        assert r.json()["status"] == "draft"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_system_admin_can_create_draft():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/faq", json={"question": "Q?", "answer": "A."})
        assert r.status_code == 201
        assert r.json()["status"] == "draft"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_faq_rejects_empty_question():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/faq", json={"question": "  ", "answer": "A."})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_create_faq_rejects_empty_answer():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/faq", json={"question": "Q?", "answer": ""})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_create_faq_status_always_draft_regardless_of_client_input():
    """Client cannot set status=approved directly on create — status is always draft."""
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Send extra field 'status' — should be ignored by Pydantic (extra fields not accepted)
            r = await client.post("/admin/faq", json={"question": "Q?", "answer": "A.", "status": "approved"})
        assert r.status_code == 201
        assert r.json()["status"] == "draft"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Approve FAQ ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_faq_sets_status_and_approver():
    actor = _user_with_roles("faq_manager")
    item = _faq_item(status="draft")
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        faq_id = str(uuid.uuid4())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{faq_id}/approve")
        assert r.status_code == 200
        assert item.status == "approved"
        assert item.approved_by_user_id == actor.id
        assert item.approved_at is not None
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Archive FAQ ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_faq_sets_status_archived():
    item = _faq_item(status="approved")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}/archive")
        assert r.status_code == 200
        assert item.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Update FAQ ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_approved_faq_returns_to_draft_and_increments_version():
    item = _faq_item(status="approved", version=2)
    item.question = "Old question?"
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(
                f"/admin/faq/{uuid.uuid4()}",
                json={"question": "Updated question?"},
            )
        assert r.status_code == 200
        assert item.status == "draft"
        assert item.content_version == 3
        assert item.approved_by_user_id is None
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_update_archived_faq_returns_422():
    item = _faq_item(status="archived")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}", json={"question": "New?"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
