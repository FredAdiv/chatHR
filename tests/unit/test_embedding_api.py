"""Admin embeddings API — authorization and endpoint tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.chunk_embedding import ChunkEmbedding
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


def _now():
    return datetime.now(timezone.utc)


def _make_index_version(status="building"):
    iv = MagicMock(spec=IndexVersion)
    iv.id = uuid.uuid4()
    iv.status = status
    return iv


def _make_chunk_embedding():
    now = _now()
    ce = MagicMock(spec=ChunkEmbedding)
    ce.id = uuid.uuid4()
    ce.document_chunk_id = uuid.uuid4()
    ce.source_document_id = uuid.uuid4()
    ce.parsed_document_id = uuid.uuid4()
    ce.index_version_id = uuid.uuid4()
    ce.embedding_model = "fake-local-v1"
    ce.embedding_dimension = 16
    ce.content_hash = "abc123"
    ce.status = "embedded"
    ce.error_message = None
    ce.created_at = now
    return ce


def _db_for_generate(index_version):
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=index_version)
    async def _dep():
        yield mock_db
    return _dep


def _db_for_list(items):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = items
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embeddings_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/embeddings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_embeddings_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_embeddings_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_embeddings_faq_manager_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /admin/embeddings/generate ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_generate():
    iv = _make_index_version(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_generate(iv)
    try:
        from app.services.embeddings.base import EmbeddingGenerationResult
        fake_result = EmbeddingGenerationResult(
            index_version_id=iv.id,
            embedding_model="fake-local-v1",
            embedding_dimension=16,
            chunks_found=0,
            embedded_count=0,
            skipped_count=0,
            failed_count=0,
        )
        with patch("app.api.admin_embeddings.embed_chunks_for_index_version", return_value=fake_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/embeddings/generate", json={"index_version_id": str(iv.id)})
        assert r.status_code == 200
        assert r.json()["embedding_model"] == "fake-local-v1"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_system_admin_can_generate():
    iv = _make_index_version(status="building")
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_for_generate(iv)
    try:
        from app.services.embeddings.base import EmbeddingGenerationResult
        fake_result = EmbeddingGenerationResult(
            index_version_id=iv.id,
            embedding_model="fake-local-v1",
            embedding_dimension=16,
            chunks_found=0,
            embedded_count=0,
            skipped_count=0,
            failed_count=0,
        )
        with patch("app.api.admin_embeddings.embed_chunks_for_index_version", return_value=fake_result):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/admin/embeddings/generate", json={"index_version_id": str(iv.id)})
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_generate_returns_409_for_non_building_version():
    iv = _make_index_version(status="ready")
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_generate(iv)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/embeddings/generate", json={"index_version_id": str(iv.id)})
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_generate_returns_404_for_missing_version():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)
    async def _dep():
        yield mock_db
    app.dependency_overrides[get_db] = _dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/embeddings/generate", json={"index_version_id": str(uuid.uuid4())})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /admin/embeddings ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_embeddings_returns_200():
    ce = _make_chunk_embedding()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([ce])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["embedding_model"] == "fake-local-v1"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_embeddings_invalid_status_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings?embedding_status=invalid")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_list_embeddings_no_raw_vector():
    ce = _make_chunk_embedding()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([ce])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/embeddings")
        assert r.status_code == 200
        item = r.json()[0]
        assert "embedding" not in item
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST /admin/embeddings/search ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_empty_query_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/embeddings/search", json={
                "index_version_id": str(uuid.uuid4()),
                "query_text": "",
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_search_limit_over_20_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/embeddings/search", json={
                "index_version_id": str(uuid.uuid4()),
                "query_text": "HR policy",
                "limit": 21,
            })
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_search_returns_200():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])

    # Mock the DB execute for vector search
    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.chunk_text = "Leave policy for civil servants"
    mock_row.source_document_id = uuid.uuid4()
    mock_row.parsed_document_id = uuid.uuid4()
    mock_row.distance = 0.1

    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter([mock_row]))

    # Mock the IndexVersion.get() to return a proper index version with string attributes
    mock_iv = MagicMock()
    mock_iv.embedding_provider = "fake-local"
    mock_iv.embedding_model = "fake-local-v1"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.get = AsyncMock(return_value=mock_iv)

    async def _dep():
        yield mock_db

    app.dependency_overrides[get_db] = _dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/admin/embeddings/search", json={
                "index_version_id": str(uuid.uuid4()),
                "query_text": "annual leave entitlement",
                "limit": 5,
            })
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
