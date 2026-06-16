"""Knowledge Sources API — authorization and behavior tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.knowledge_source import KnowledgeSource
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
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_get(item):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=item)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_list(items=None):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = items or []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


def _ks_item(is_active=True, authority_level=2):
    now = datetime.now(timezone.utc)
    item = MagicMock(spec=KnowledgeSource)
    item.id = uuid.uuid4()
    item.name = "תקשי\"ר"
    item.source_type = "civil_service_regulations"
    item.url = "https://example.gov.il/takshir"
    item.authority_level = authority_level
    item.is_active = is_active
    item.created_at = now
    item.updated_at = now
    return item


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ks_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/knowledge-sources")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_ks_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/knowledge-sources")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_ks_user_admin_alone_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={"name": "X", "source_type": "Y", "authority_level": 1})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_ks_faq_manager_alone_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/knowledge-sources")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Create ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_create_source():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={
                "name": "תקשי\"ר",
                "source_type": "civil_service_regulations",
                "authority_level": 1,
            })
        assert r.status_code == 201
        assert r.json()["authority_level"] == 1
        assert r.json()["is_active"] is True
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_system_admin_can_create_source():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={
                "name": "Salary Agreement",
                "source_type": "salary_agreement",
                "authority_level": 2,
            })
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authority_level_0_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={"name": "X", "source_type": "Y", "authority_level": 0})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_authority_level_6_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={"name": "X", "source_type": "Y", "authority_level": 6})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_empty_name_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={"name": "  ", "source_type": "Y", "authority_level": 1})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_empty_source_type_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/knowledge-sources", json={"name": "X", "source_type": "", "authority_level": 1})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_list_sources():
    item = _ks_item()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([item])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/knowledge-sources")
        assert r.status_code == 200
        assert len(r.json()) == 1
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Deactivate / Activate ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deactivate_sets_is_active_false():
    item = _ks_item(is_active=True)
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/knowledge-sources/{uuid.uuid4()}/deactivate")
        assert r.status_code == 200
        assert item.is_active is False
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_sets_is_active_true():
    item = _ks_item(is_active=False)
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/knowledge-sources/{uuid.uuid4()}/activate")
        assert r.status_code == 200
        assert item.is_active is True
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
