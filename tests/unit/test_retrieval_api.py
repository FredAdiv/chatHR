"""Admin retrieval API — authorization and endpoint tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.main import app
from app.services.retrieval.retriever import RetrievedChunk
from app.services.retrieval.citation import CitationMetadata


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


def _make_retrieved_chunk():
    citation = CitationMetadata(
        source_url="https://example.gov.il/doc.pdf",
        source_title="Leave Policy",
        knowledge_source_id=str(uuid.uuid4()),
        knowledge_source_name="Civil Service Commission",
        authority_level=2,
        section_title=None,
        page_number=None,
        chunk_index=0,
        document_type="pdf",
    )
    return RetrievedChunk(
        chunk_id=str(uuid.uuid4()),
        chunk_text="Annual leave regulations for civil servants.",
        parsed_document_id=str(uuid.uuid4()),
        source_document_id=str(uuid.uuid4()),
        distance=0.2,
        score=0.8,
        citation=citation,
    )


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
async def test_retrieval_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/retrieval/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_retrieval_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/retrieval/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_retrieval_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/retrieval/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_retrieval_faq_manager_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/retrieval/health")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── GET /admin/retrieval/health ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/retrieval/health")
        assert r.status_code == 200
        data = r.json()
        assert data["embedding_model"] == "fake-local-v1"
        assert data["embedding_dimension"] == 16
        assert data["vector_search_available"] is True
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_health_system_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/retrieval/health")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /admin/retrieval/search ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_empty_query_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/retrieval/search", json={
                "query_text": "",
                "index_version_id": str(uuid.uuid4()),
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_search_limit_over_20_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/retrieval/search", json={
                "query_text": "leave policy",
                "index_version_id": str(uuid.uuid4()),
                "limit": 21,
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_search_invalid_context_type_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/retrieval/search", json={
                "query_text": "leave policy",
                "index_version_id": str(uuid.uuid4()),
                "context_type": "invalid_sector",
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_search_returns_200_with_citation_metadata():
    chunk = _make_retrieved_chunk()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        with patch("app.api.admin_retrieval.retrieve_chunks", return_value=[chunk]):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/retrieval/search", json={
                    "query_text": "annual leave regulations",
                    "index_version_id": str(uuid.uuid4()),
                })
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        item = items[0]
        assert item["chunk_text"] == "Annual leave regulations for civil servants."
        assert "citation" in item
        assert item["citation"]["authority_level"] == 2
        assert item["citation"]["knowledge_source_name"] == "Civil Service Commission"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_search_knowledge_admin_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        with patch("app.api.admin_retrieval.retrieve_chunks", return_value=[]):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/retrieval/search", json={
                    "query_text": "recruitment policy",
                    "index_version_id": str(uuid.uuid4()),
                })
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_search_audit_does_not_include_query_text():
    """Verify audit metadata passed to record_audit_event does not contain query_text."""
    chunk = _make_retrieved_chunk()
    captured_meta = {}

    async def _fake_audit(db, *, action, actor_user_id, target_type, target_id, metadata_json=None):
        captured_meta.update(metadata_json or {})

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_noop()
    try:
        with patch("app.api.admin_retrieval.retrieve_chunks", return_value=[chunk]), \
             patch("app.api.admin_retrieval.record_audit_event", side_effect=_fake_audit):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post("/admin/retrieval/search", json={
                    "query_text": "sensitive HR search query",
                    "index_version_id": str(uuid.uuid4()),
                })
        meta_str = str(captured_meta)
        assert "sensitive HR search query" not in meta_str
        assert "query_text" not in meta_str
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
