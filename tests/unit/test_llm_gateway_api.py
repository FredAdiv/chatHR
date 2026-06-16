"""Admin LLM Gateway API — authorization and endpoint tests."""
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


def _db_noop():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gateway_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/llm-gateway/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_gateway_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/llm-gateway/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_gateway_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/llm-gateway/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_gateway_knowledge_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/llm-gateway/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── GET /admin/llm-gateway/health ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/llm-gateway/health")
        assert r.status_code == 200
        data = r.json()
        assert data["privacy_guard_enabled"] is True
        assert "provider_configured" in data
        assert "default_model" in data
        assert "fallback_model_configured" in data
        assert "openrouter_configured" in data
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_health_does_not_return_api_key():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/llm-gateway/health")
        data = r.json()
        response_str = str(data)
        # No key values — only a boolean presence indicator
        assert "CHANGE_ME" not in response_str
        assert "openrouter_api_key" not in response_str
        assert "sk-" not in response_str
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /admin/llm-gateway/test-generate ────────────────────────────────────

@pytest.mark.asyncio
async def test_test_generate_safe_message_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/llm-gateway/test-generate", json={
                "message": "What is the annual leave policy for civil servants?",
                "purpose": "debug",
            })
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert "model" in data
        assert "provider" in data
        assert "[fake-local]" in data["content"]
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_test_generate_pii_blocked_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/llm-gateway/test-generate", json={
                "message": "Employee email: hr@ministry.gov.il please help",
            })
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["error"] == "privacy_guard_blocked"
        assert "findings" in detail
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_test_generate_findings_do_not_expose_matched_text():
    """422 findings must NOT contain raw sensitive text (matched_text field absent)."""
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/llm-gateway/test-generate", json={
                "message": "Phone: 052-1111111",
            })
        assert r.status_code == 422
        findings = r.json()["detail"]["findings"]
        for f in findings:
            assert "matched_text" not in f
            assert "052-1111111" not in str(f)
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_test_generate_empty_message_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/llm-gateway/test-generate", json={"message": ""})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── Model integrity ───────────────────────────────────────────────────────────

def test_llm_usage_log_has_no_prompt_columns():
    """LLMUsageLog must not have columns that could store prompts."""
    from app.db.models.llm_usage_log import LLMUsageLog
    cols = {c.name for c in LLMUsageLog.__table__.columns}
    forbidden = {"prompt", "message", "messages", "user_text", "input_text", "query_text", "content"}
    assert not (cols & forbidden), f"Forbidden columns found: {cols & forbidden}"


def test_llm_usage_log_status_constraint_present():
    from app.db.models.llm_usage_log import LLMUsageLog
    constraint_names = {c.name for c in LLMUsageLog.__table__.constraints}
    assert "ck_llm_usage_logs_status" in constraint_names


def test_llm_usage_log_registered_in_models_init():
    from app.db import models
    assert hasattr(models, "LLMUsageLog")
    assert models.LLMUsageLog is not None
