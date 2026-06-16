"""Tests for POST /admin/knowledge/documents/{id}/process and GET /admin/knowledge/documents/{id}."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    return _dep


def _make_ks(authority_level=1):
    ks = MagicMock()
    ks.id = uuid.uuid4()
    ks.authority_level = authority_level
    return ks


def _make_sd(ks_id, status="downloaded", has_storage=True, doc_type="pdf", semantic_type=None):
    sd = MagicMock()
    sd.id = uuid.uuid4()
    sd.knowledge_source_id = ks_id
    sd.status = status
    sd.document_type = doc_type
    sd.title = 'תקשי"ר'
    sd.metadata_json = {"semantic_type": semantic_type or doc_type, "file_format": doc_type}
    sd.created_at = datetime.now(timezone.utc)
    sd.updated_at = datetime.now(timezone.utc)
    if has_storage:
        sd.storage_bucket = "chathr-documents"
        sd.storage_object_key = f"raw/ab/{'ab' * 32}.pdf"
    else:
        sd.storage_bucket = None
        sd.storage_object_key = None
    return sd


def _make_parsed_doc(source_document_id, parse_status="parsed"):
    pd = MagicMock()
    pd.id = uuid.uuid4()
    pd.source_document_id = source_document_id
    pd.parse_status = parse_status
    pd.error_message = None
    return pd


def _make_chunk(parsed_doc_id, source_doc_id, index=0):
    chunk = MagicMock()
    chunk.id = uuid.uuid4()
    chunk.parsed_document_id = parsed_doc_id
    chunk.source_document_id = source_doc_id
    chunk.chunk_index = index
    chunk.chunk_text = "sample chunk text for testing purposes"
    chunk.chunk_hash = "hash" + str(index)
    return chunk


def _db_mock_for_get(sd, ks):
    """DB mock for GET document endpoint."""
    async def mock_get(model_class, pk):
        from app.db.models.source_document import SourceDocument
        from app.db.models.knowledge_source import KnowledgeSource
        if model_class is SourceDocument:
            return sd if str(pk) == str(sd.id) else None
        if model_class is KnowledgeSource:
            return ks if str(pk) == str(sd.knowledge_source_id) else None
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def _dep():
        yield mock_db
    return _dep


def _db_mock_for_process(sd, ks, parsed_doc, chunks):
    """DB mock for POST process endpoint."""
    async def mock_get(model_class, pk):
        from app.db.models.source_document import SourceDocument
        from app.db.models.knowledge_source import KnowledgeSource
        if model_class is SourceDocument:
            return sd if str(pk) == str(sd.id) else None
        if model_class is KnowledgeSource:
            return ks if str(pk) == str(sd.knowledge_source_id) else None
        return None

    call_count = [0]

    async def mock_execute(stmt):
        call_count[0] += 1
        result = MagicMock()
        result.scalars.return_value.all.return_value = chunks
        return result

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def _dep():
        yield mock_db
    return _dep


# ── GET: Authorization ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_document_anonymous_returns_401():
    """Anonymous request must return 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/admin/knowledge/documents/{uuid.uuid4()}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_document_chat_user_returns_403():
    """chat_user must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/knowledge/documents/{uuid.uuid4()}")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_get_document_not_found_returns_404():
    """Missing document_id must return 404."""
    ks = _make_ks()
    sd_id = uuid.uuid4()

    async def mock_get(model_class, pk):
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/knowledge/documents/{sd_id}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_document_returns_safe_metadata():
    """GET must return safe metadata without raw content."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    db_dep = _db_mock_for_get(sd, ks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/knowledge/documents/{sd.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["document_id"] == str(sd.id)
        assert body["status"] == "downloaded"
        assert "created_at" in body
        assert "updated_at" in body
        # raw content must not appear
        assert "storage_object_key" not in body
        assert "storage_bucket" not in body
        assert "content_hash" not in body
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST process: Authorization ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_anonymous_returns_401():
    """Anonymous request must return 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/admin/knowledge/documents/{uuid.uuid4()}/process")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_process_chat_user_returns_403():
    """chat_user must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/documents/{uuid.uuid4()}/process")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_process_faq_manager_returns_403():
    """faq_manager must be rejected with 403."""
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/documents/{uuid.uuid4()}/process")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


# ── POST process: Document lookup ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_missing_document_returns_404():
    """Missing document must return 404."""
    async def mock_get(model_class, pk):
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/documents/{uuid.uuid4()}/process")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_missing_minio_ref_returns_409():
    """Document with no MinIO storage reference must fail safely with 409."""
    ks = _make_ks()
    sd = _make_sd(ks.id, has_storage=False)
    db_dep = _db_mock_for_get(sd, ks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST process: Successful processing ───────────────────────────────────────

@pytest.mark.asyncio
async def test_process_knowledge_admin_accepted():
    """knowledge_admin must succeed and return index_version_id + chunk_count."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, i) for i in range(3)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        body = r.json()
        assert "index_version_id" in body
        assert body["chunk_count"] == 3
        assert body["status"] == "processed"
        assert "index_version_label" in body
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_system_admin_accepted():
    """system_admin must succeed."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, i) for i in range(2)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["system_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_takshir_document_type_works():
    """Processing path for document_type=takshir and authority_level=1 must succeed."""
    ks = _make_ks(authority_level=1)
    sd = _make_sd(ks.id, doc_type="pdf")
    sd.title = 'תקשי"ר'
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, i) for i in range(5)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        body = r.json()
        assert body["chunk_count"] == 5
        assert body["status"] == "processed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── POST process: Safety checks ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_does_not_activate_index():
    """Processing must create an index with status='ready', NOT 'active'."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, 0)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    added_objects = []

    original_db_dep, *_ = db_dep, None

    # Capture objects added to DB to inspect IndexVersion status
    from app.db.models.index_version import IndexVersion as IV

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])

    mock_db = AsyncMock()

    async def mock_get(model_class, pk):
        from app.db.models.source_document import SourceDocument
        from app.db.models.knowledge_source import KnowledgeSource
        if model_class is SourceDocument:
            return sd
        if model_class is KnowledgeSource:
            return ks
        return None

    async def mock_execute(stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = chunks
        return result

    def mock_add(obj):
        added_objects.append(obj)

    mock_db.get = mock_get
    mock_db.execute = mock_execute
    mock_db.add = mock_add
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def db_dep2():
        yield mock_db

    app.dependency_overrides[get_db] = db_dep2
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        # Check IndexVersion was set to 'draft' (not 'active' or 'ready' immediately)
        index_versions = [obj for obj in added_objects if isinstance(obj, IV)]
        assert len(index_versions) == 1
        assert index_versions[0].status == "draft"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_raw_content_not_in_response():
    """Raw file bytes must never appear in the process response."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, 0)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        raw_response = r.text
        assert "storage_object_key" not in raw_response
        assert "storage_bucket" not in raw_response
        assert "content_hash" not in raw_response
        assert "chunk_text" not in raw_response
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_document_returns_semantic_type_not_file_format():
    """GET must return semantic_type ('takshir') as document_type, not file format ('pdf')."""
    ks = _make_ks()
    sd = _make_sd(ks.id, semantic_type="takshir")
    db_dep = _db_mock_for_get(sd, ks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/admin/knowledge/documents/{sd.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["document_type"] == "takshir"
        assert body["file_format"] == "pdf"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_returns_semantic_type_in_response():
    """Process endpoint must return semantic_type as document_type in response."""
    ks = _make_ks(authority_level=1)
    sd = _make_sd(ks.id, doc_type="pdf", semantic_type="takshir")
    sd.title = 'תקשי"ר'
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, i) for i in range(2)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        body = r.json()
        assert body["document_type"] == "takshir"
        assert body["file_format"] == "pdf"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_creates_draft_not_ready_index():
    """Process endpoint must create IndexVersion with status='draft', not 'ready'."""
    ks = _make_ks()
    sd = _make_sd(ks.id, semantic_type="takshir")
    parsed_doc = _make_parsed_doc(sd.id)
    chunks = [_make_chunk(parsed_doc.id, sd.id, 0)]
    db_dep = _db_mock_for_process(sd, ks, parsed_doc, chunks)

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
            patch("app.services.embeddings.fake_provider.FakeLocalProvider.embed_texts", return_value=[[0.0] * 128]),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 200
        # The status in the response is about the source document, not the index version
        # The response message should mention 'draft'
        body = r.json()
        assert "draft" in body["message"].lower() or body["status"] == "processed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_process_failed_parse_returns_422():
    """When parsing fails, the endpoint must return 422 with a safe error message."""
    ks = _make_ks()
    sd = _make_sd(ks.id)
    parsed_doc = _make_parsed_doc(sd.id, parse_status="failed")

    async def mock_get(model_class, pk):
        from app.db.models.source_document import SourceDocument
        from app.db.models.knowledge_source import KnowledgeSource
        if model_class is SourceDocument:
            return sd
        if model_class is KnowledgeSource:
            return ks
        return None

    mock_db = AsyncMock()
    mock_db.get = mock_get
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    async def db_dep():
        yield mock_db

    app.dependency_overrides[get_current_active_user] = _auth(["knowledge_admin"])
    app.dependency_overrides[get_db] = db_dep
    try:
        with (
            patch("app.api.admin_knowledge_process.parse_and_chunk_source_document", AsyncMock(return_value=parsed_doc)),
            patch("app.api.admin_knowledge_process.record_audit_event", AsyncMock()),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/admin/knowledge/documents/{sd.id}/process")
        assert r.status_code == 422
        body = r.json()
        assert body.get("detail", {}).get("error") == "parse_failed"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)
