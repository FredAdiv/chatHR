"""Part A: Route-level authorization tests for auth-sensitive endpoints."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.main import app


def _user_with_roles(*role_names):
    """Return a mock User carrying the given roles."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_active = True
    user.user_roles = [SimpleNamespace(role=SimpleNamespace(name=r)) for r in role_names]
    return user


def _auth(roles):
    """Dependency override returning a user with given roles."""
    u = _user_with_roles(*roles)
    def _dep():
        return u
    return _dep


def _db_returning_empty_users():
    """get_db override: returns empty scalars for list-users query."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


def _db_returning_role_count(count=6):
    """get_db override: returns a scalar for SELECT COUNT(*) FROM roles."""
    mock_result = MagicMock()
    mock_result.scalar.return_value = count
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


# ── /admin/users ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_users_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/users")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_users_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/users")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_users_user_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    app.dependency_overrides[get_db] = _db_returning_empty_users()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/users")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_users_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_returning_empty_users()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/users")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── /dev/db-info ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dev_db_info_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/dev/db-info")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_dev_db_info_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/dev/db-info")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_dev_db_info_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_returning_role_count()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/dev/db-info")
        assert r.status_code == 200
        assert r.json()["status"] == "connected"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── existing invariants ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_remains_public():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_me_still_requires_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/auth/me")
    assert r.status_code == 401
