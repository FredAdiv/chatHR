"""Index Versions API — authorization and lifecycle tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.index_version import IndexVersion
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
    """For simple endpoints that only call db.get()."""
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=item)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _db_for_activate(target_iv, current_active_ivs=None):
    """For activate endpoint: db.get returns target, db.execute returns current active versions."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = current_active_ivs or []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=target_iv)
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


def _iv(status="building"):
    now = datetime.now(timezone.utc)
    item = MagicMock(spec=IndexVersion)
    item.id = uuid.uuid4()
    item.version_label = f"v1.0-{status}"
    item.status = status
    item.embedding_model = "text-embedding-ada-002"
    item.embedding_provider = "fake-local"
    item.embedding_dimensions = 16
    item.created_by_user_id = uuid.uuid4()
    item.activated_by_user_id = None
    item.created_at = now
    item.activated_at = None
    item.metadata_json = None
    return item


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_iv_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/index-versions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_iv_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/index-versions")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_iv_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/index-versions")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_iv_faq_manager_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/index-versions")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_create_version_in_building_status():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/index-versions", json={
                "version_label": "v1.0-20260616",
                "embedding_model": "text-embedding-ada-002",
            })
        assert r.status_code == 201
        assert r.json()["status"] == "building"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_version_status_always_building():
    """Client cannot bypass building status by sending extra fields."""
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_create()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/index-versions", json={
                "version_label": "v2.0",
                "embedding_model": "text-embedding-ada-002",
                "status": "active",  # should be ignored
            })
        assert r.status_code == 201
        assert r.json()["status"] == "building"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── mark-ready ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_ready_from_building_succeeds():
    iv = _iv(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-ready")
        assert r.status_code == 200
        assert iv.status == "ready"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_mark_ready_from_ready_returns_409():
    iv = _iv(status="ready")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-ready")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── activate ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_from_ready_succeeds():
    actor = _user_with_roles("knowledge_admin")
    iv = _iv(status="ready")
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db] = _db_for_activate(iv, current_active_ivs=[])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 200
        assert iv.status == "active"
        assert iv.activated_by_user_id == actor.id
        assert iv.activated_at is not None
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_archives_previous_active_version():
    actor = _user_with_roles("knowledge_admin")
    target_iv = _iv(status="ready")
    old_active_iv = _iv(status="active")
    app.dependency_overrides[get_current_active_user] = lambda: actor
    app.dependency_overrides[get_db] = _db_for_activate(target_iv, current_active_ivs=[old_active_iv])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 200
        assert target_iv.status == "active"
        assert old_active_iv.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_building_returns_409():
    iv = _iv(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_activate(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_quality_check_failed_returns_409():
    iv = _iv(status="quality_check_failed")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_activate(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_activate_archived_returns_409():
    iv = _iv(status="archived")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_activate(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/activate")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── archive ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_archive_ready_version_succeeds():
    iv = _iv(status="ready")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/archive")
        assert r.status_code == 200
        assert iv.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_archive_quality_failed_version_succeeds():
    iv = _iv(status="quality_check_failed")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/archive")
        assert r.status_code == 200
        assert iv.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_archive_active_version_directly_returns_409():
    iv = _iv(status="active")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/archive")
        assert r.status_code == 409
        assert iv.status == "active"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_archive_building_version_returns_409():
    iv = _iv(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/archive")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── mark-quality-failed allowed statuses (Fix 2) ─────────────────────────────

@pytest.mark.asyncio
async def test_mark_quality_failed_from_building_succeeds():
    iv = _iv(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-quality-failed")
        assert r.status_code == 200
        assert iv.status == "quality_check_failed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_mark_quality_failed_from_ready_succeeds():
    iv = _iv(status="ready")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-quality-failed")
        assert r.status_code == 200
        assert iv.status == "quality_check_failed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_mark_quality_failed_from_archived_returns_409():
    iv = _iv(status="archived")
    original_status = iv.status
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-quality-failed")
        assert r.status_code == 409
        assert iv.status == original_status
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_mark_quality_failed_from_active_returns_409():
    iv = _iv(status="active")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-quality-failed")
        assert r.status_code == 409
        assert iv.status == "active"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_mark_quality_failed_from_quality_check_failed_returns_409():
    iv = _iv(status="quality_check_failed")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/index-versions/{uuid.uuid4()}/mark-quality-failed")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
