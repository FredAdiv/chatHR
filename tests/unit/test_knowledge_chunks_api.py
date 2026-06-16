"""Tests for GET /knowledge/chunks/{chunk_id} — safe citation viewer endpoint."""
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
    return _dep, u


def _make_chunk_row(chunk_id=None, source_doc_id=None, ks_id=None):
    """Build a fake row tuple (chunk, source_doc, knowledge_source)."""
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.chunk_text = "הוראות התקשי\"ר חלות על כל סוגי העובדים בשירות המדינה."
    chunk.section_title = "01.021 — תחולה"
    chunk.page_number = 5
    chunk.chunk_index = 0

    source_doc = MagicMock()
    source_doc.id = source_doc_id or uuid.uuid4()
    source_doc.title = 'תקשי"ר'
    source_doc.document_type = "takshir"

    ks = MagicMock()
    ks.id = ks_id or uuid.uuid4()
    ks.name = "נציבות שירות המדינה"
    ks.authority_level = 1

    return (chunk, source_doc, ks)


def _db_with_row(row):
    """DB mock that returns a single row from execute().first()."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = row
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _dep():
        yield mock_db
    return _dep


def _db_with_no_row():
    """DB mock that returns None from execute().first()."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _dep():
        yield mock_db
    return _dep


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunk_viewer_anonymous_returns_401():
    """Anonymous users must be rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/knowledge/chunks/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_chunk_viewer_knowledge_admin_can_access():
    """knowledge_admin must be able to access the chunk viewer."""
    dep, _ = _auth(["knowledge_admin"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_feedback_reviewer_cannot_access_returns_403():
    """feedback_reviewer without any of the viewer roles must not access chunk viewer."""
    dep, _ = _auth(["feedback_reviewer"])
    app.dependency_overrides[get_current_active_user] = dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{uuid.uuid4()}")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_chunk_viewer_chat_user_can_access():
    """chat_user must be able to access the chunk viewer."""
    dep, _ = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_system_admin_can_access():
    """system_admin must be able to access the chunk viewer."""
    dep, _ = _auth(["system_admin"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── 404 handling ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunk_viewer_missing_chunk_returns_404():
    """Non-existent chunk must return 404, not 500."""
    dep, _ = _auth(["chat_user"])
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_no_row()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Response content ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunk_viewer_returns_safe_metadata():
    """Response must include title, authority_level, document_type, section_title, page_number."""
    dep, _ = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["chunk_id"] == str(chunk_id)
        assert data["source_title"] == 'תקשי"ר'
        assert data["document_type"] == "takshir"
        assert data["authority_level"] == 1
        assert data["knowledge_source_name"] == "נציבות שירות המדינה"
        assert data["section_title"] == "01.021 — תחולה"
        assert data["page_number"] == 5
        assert data["chunk_index"] == 0
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_returns_excerpt():
    """Response must include the chunk text excerpt."""
    dep, _ = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        data = r.json()
        assert "excerpt" in data
        assert "חלות על כל סוגי העובדים" in data["excerpt"]
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_does_not_expose_minio_key():
    """Response must not expose MinIO object keys or storage paths."""
    dep, _ = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        data = r.json()
        response_str = str(data)
        assert "storage_bucket" not in response_str
        assert "storage_object_key" not in response_str
        assert "raw/" not in response_str
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_truncates_long_excerpt():
    """Excerpt must be truncated to at most 1000 chars + ellipsis for long chunk text."""
    dep, _ = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_chunk_row(chunk_id=chunk_id)
    long_text = "א" * 2000
    row[0].chunk_text = long_text  # override the chunk text
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        data = r.json()
        excerpt = data["excerpt"]
        assert len(excerpt) <= 1004  # 1000 + "..."
        assert excerpt.endswith("...")
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_chunk_viewer_route_registered_not_404():
    """Route must be registered (returns 401, not 404)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/knowledge/chunks/{uuid.uuid4()}")
    assert r.status_code != 404, "Route not registered — got 404"
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_citation_link_points_to_internal_route():
    """Verifies the chunk viewer endpoint returns HTTP 401 (not blank/404) for the /knowledge/chunks/ path — confirming the route exists."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/knowledge/chunks/{uuid.uuid4()}")
    assert r.status_code == 401
