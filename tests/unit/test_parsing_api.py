"""Parsing API — authorization and endpoint tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_active_user
from app.db.models.document_chunk import DocumentChunk
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
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


def _now_str():
    return datetime.now(timezone.utc).isoformat()


def _make_parsed_doc(parse_status="parsed"):
    now = datetime.now(timezone.utc)
    pd = MagicMock(spec=ParsedDocument)
    pd.id = uuid.uuid4()
    pd.source_document_id = uuid.uuid4()
    pd.parser_name = "html"
    pd.parser_version = "1.0"
    pd.text_hash = "abc123"
    pd.language = None
    pd.parse_status = parse_status
    pd.error_message = None
    pd.metadata_json = {}
    pd.created_at = now
    pd.updated_at = now
    return pd


def _make_source_doc(status="downloaded"):
    now = datetime.now(timezone.utc)
    sd = MagicMock(spec=SourceDocument)
    sd.id = uuid.uuid4()
    sd.status = status
    sd.storage_bucket = "chathr-documents"
    sd.storage_object_key = "src/abc/html"
    sd.document_type = "html"
    sd.created_at = now
    sd.updated_at = now
    return sd


def _db_for_post(source_doc, parsed_doc):
    """DB mock for POST /admin/parsing/source-documents/{id}/parse."""
    mock_result_chunks = MagicMock()
    mock_result_chunks.scalars.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=lambda model, pk: source_doc if model is SourceDocument else parsed_doc)
    mock_db.execute = AsyncMock(return_value=mock_result_chunks)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

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


def _db_for_get(pd, chunks=None):
    mock_result_chunks = MagicMock()
    mock_result_chunks.scalars.return_value.all.return_value = chunks or []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=pd)
    mock_db.execute = AsyncMock(return_value=mock_result_chunks)
    async def _dep():
        yield mock_db
    return _dep


# ── Authorization ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parsing_unauthenticated_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/admin/parsing/parsed-documents")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_parsing_chat_user_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/parsing/parsed-documents")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_parsing_user_admin_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["user_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/parsing/parsed-documents")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_parsing_faq_manager_returns_403():
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/parsing/parsed-documents")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST /admin/parsing/source-documents/{id}/parse ──────────────────────────

@pytest.mark.asyncio
async def test_knowledge_admin_can_parse():
    source_doc = _make_source_doc()
    parsed_doc = _make_parsed_doc()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_post(source_doc, parsed_doc)
    try:
        with patch("app.api.admin_parsing.parse_and_chunk_source_document", return_value=parsed_doc):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/parsing/source-documents/{source_doc.id}/parse")
        assert r.status_code == 201
        assert r.json()["parse_status"] == "parsed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_system_admin_can_parse():
    source_doc = _make_source_doc()
    parsed_doc = _make_parsed_doc()
    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = _db_for_post(source_doc, parsed_doc)
    try:
        with patch("app.api.admin_parsing.parse_and_chunk_source_document", return_value=parsed_doc):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/parsing/source-documents/{source_doc.id}/parse")
        assert r.status_code == 201
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_parse_missing_source_doc_returns_404():
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=None)
    async def _dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/parsing/source-documents/{uuid.uuid4()}/parse")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_parse_discovered_doc_returns_409():
    source_doc = _make_source_doc(status="discovered")
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=source_doc)
    async def _dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/parsing/source-documents/{source_doc.id}/parse")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /admin/parsing/parsed-documents ──────────────────────────────────────

@pytest.mark.asyncio
async def test_list_parsed_documents_returns_200():
    pd = _make_parsed_doc()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_list([pd])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/parsing/parsed-documents")
        assert r.status_code == 200
        assert len(r.json()) == 1
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_parsed_documents_invalid_status_returns_422():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/admin/parsing/parsed-documents?parse_status=invalid")
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── GET /admin/parsing/parsed-documents/{id} ─────────────────────────────────

@pytest.mark.asyncio
async def test_get_parsed_document_returns_200():
    pd = _make_parsed_doc()
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(pd)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/parsing/parsed-documents/{pd.id}")
        assert r.status_code == 200
        assert r.json()["parse_status"] == "parsed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_parsed_document_missing_returns_404():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/parsing/parsed-documents/{uuid.uuid4()}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── GET /admin/parsing/parsed-documents/{id}/chunks ─────────────────────────

@pytest.mark.asyncio
async def test_list_chunks_returns_200():
    pd = _make_parsed_doc()
    now = datetime.now(timezone.utc)
    chunk = MagicMock(spec=DocumentChunk)
    chunk.id = uuid.uuid4()
    chunk.parsed_document_id = pd.id
    chunk.source_document_id = pd.source_document_id
    chunk.chunk_index = 0
    chunk.chunk_text = "Government policy excerpt"
    chunk.chunk_hash = "hash123"
    chunk.section_title = None
    chunk.page_number = None
    chunk.token_estimate = 6
    chunk.created_at = now

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(pd, chunks=[chunk])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/parsing/parsed-documents/{pd.id}/chunks")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["chunk_text"] == "Government policy excerpt"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_chunks_missing_parsed_doc_returns_404():
    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = _db_for_get(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/parsing/parsed-documents/{uuid.uuid4()}/chunks")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
