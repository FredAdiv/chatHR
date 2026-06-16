"""Targeted RBAC tests for new admin_feedback and admin_audit_logs endpoints."""
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


def _empty_db():
    """get_db override returning empty result sets for list queries."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


# ── /admin/feedback ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_feedback_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/feedback")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_feedback_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_feedback_feedback_reviewer_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["feedback_reviewer"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 0
        assert body["items"] == []
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_feedback_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_feedback_knowledge_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_feedback_rating_filter_accepted():
    app.dependency_overrides[get_current_active_user] = _auth(["feedback_reviewer"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback?rating=positive")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_feedback_invalid_rating_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["feedback_reviewer"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/feedback?rating=invalid")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── /admin/audit-logs ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_audit_logs_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/audit-logs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_audit_logs_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/audit-logs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_audit_logs_feedback_reviewer_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["feedback_reviewer"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/audit-logs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_audit_logs_knowledge_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/audit-logs")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_admin_audit_logs_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/audit-logs")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert body["items"] == []
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_admin_audit_logs_action_filter_accepted():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _empty_db()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/audit-logs?action=conversation_created")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
