"""Tests for /auth/* endpoints."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_me_without_token_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_non_uuid_jwt_sub_returns_401():
    """A validly signed JWT whose sub is not a UUID must return 401, not 500."""
    payload = {"sub": "not-a-uuid", "exp": datetime.now(timezone.utc) + timedelta(minutes=60)}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_list_users_without_token_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dev_db_info_without_token_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/dev/db-info")
    assert response.status_code == 401


def _make_db_override(user_or_none):
    """Return a get_db dependency override that yields a mocked session returning user_or_none."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user_or_none
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    async def _override():
        yield mock_db

    return _override


@pytest.mark.asyncio
async def test_login_unknown_email_returns_generic_401():
    app.dependency_overrides[get_db] = _make_db_override(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/auth/login", data={"username": "nobody@example.com", "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_login_inactive_user_returns_generic_401():
    inactive_user = MagicMock()
    inactive_user.is_active = False
    inactive_user.password_hash = "irrelevant"
    app.dependency_overrides[get_db] = _make_db_override(inactive_user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/auth/login", data={"username": "inactive@example.com", "password": "anypass"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_login_wrong_password_returns_generic_401():
    import bcrypt
    hashed = bcrypt.hashpw(b"correct", bcrypt.gensalt()).decode()
    active_user = MagicMock()
    active_user.is_active = True
    active_user.password_hash = hashed
    app.dependency_overrides[get_db] = _make_db_override(active_user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/auth/login", data={"username": "user@example.com", "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    finally:
        app.dependency_overrides.pop(get_db, None)
