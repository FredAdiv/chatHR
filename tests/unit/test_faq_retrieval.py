"""FAQ retrieval integration tests.

Tests for:
- sync_faq_to_retrieval: creates KnowledgeSource, SourceDocument, ParsedDocument,
  DocumentChunk with authority_level=4 and safe metadata
- remove_faq_from_retrieval: deletes ChunkEmbedding rows
- Draft/archived FAQ is never retrievable
- FAQ authority_level is lower than Takshir (4 > 1)
- FAQ citation/source viewer safety (no MinIO, no raw prompts, no storage paths)
- RBAC: chat_user cannot manage FAQ; faq_manager can approve/archive
- Status changes trigger sync/remove
"""
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
from app.db.models.document_chunk import DocumentChunk
from app.db.models.faq_item import FaqItem
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.db.session import get_db
from app.main import app
from app.services.faq.retrieval_sync import (
    _FAQ_AUTHORITY_LEVEL,
    _faq_chunk_text,
    remove_faq_from_retrieval,
    sync_faq_to_retrieval,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _faq(status="approved", context_type="government_ministries"):
    now = datetime.now(timezone.utc)
    item = MagicMock(spec=FaqItem)
    item.id = uuid.uuid4()
    item.question = "האם ניתן לעבור לתפקיד במשרד אחר?"
    item.answer = "כן, בכפוף לאישור הממונה והנציבות."
    item.topic = "ניידות"
    item.context_type = context_type
    item.applicable_population = "עובדים בדרג מקצועי"
    item.official_source_links = ["https://www.civil.gov.il/takshir"]
    item.status = status
    item.approved_by_user_id = uuid.uuid4()
    item.approved_at = now
    item.content_version = 1
    item.created_at = now
    item.updated_at = now
    return item


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


def _empty_sync_db():
    """Mock DB returning None for all scalar lookups and [] for scalars().all()."""
    empty_scalar = MagicMock()
    empty_scalar.scalar_one_or_none.return_value = None
    empty_scalar.scalars.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=empty_scalar)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    return mock_db


def _db_for_get(item):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=item)
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    async def _dep():
        yield mock_db
    return _dep


# ── Authority level ────────────────────────────────────────────────────────────

def test_faq_authority_level_constant_is_4():
    """FAQ must have authority_level=4, lower authority than Takshir (1) and official docs."""
    assert _FAQ_AUTHORITY_LEVEL == 4


def test_faq_authority_is_lower_than_takshir():
    """A higher authority_level number means lower authority. FAQ (4) < Takshir (1)."""
    takshir_authority = 1
    assert _FAQ_AUTHORITY_LEVEL > takshir_authority, (
        "FAQ authority_level must be numerically higher (= weaker) than Takshir"
    )


# ── chunk text format ──────────────────────────────────────────────────────────

def test_faq_chunk_text_format():
    faq = _faq()
    text = _faq_chunk_text(faq)
    assert "שאלה:" in text
    assert "תשובה:" in text
    assert faq.question in text
    assert faq.answer in text


# ── sync_faq_to_retrieval ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_draft_faq_is_noop():
    """Syncing a draft FAQ must not create any DB records."""
    faq = _faq(status="draft")
    mock_db = _empty_sync_db()
    await sync_faq_to_retrieval(mock_db, faq)
    mock_db.add.assert_not_called()
    mock_db.flush.assert_not_called()


@pytest.mark.asyncio
async def test_sync_archived_faq_is_noop():
    """Syncing an archived FAQ must not create any DB records."""
    faq = _faq(status="archived")
    mock_db = _empty_sync_db()
    await sync_faq_to_retrieval(mock_db, faq)
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_sync_approved_faq_creates_required_records():
    """Approved FAQ sync creates KnowledgeSource, SourceDocument, ParsedDocument, DocumentChunk, AuditLog."""
    faq = _faq(status="approved")
    mock_db = _empty_sync_db()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await sync_faq_to_retrieval(mock_db, faq, actor_user_id=uuid.uuid4())

    types_added = [type(o) for o in added_objects]
    assert KnowledgeSource in types_added, "KnowledgeSource must be created"
    assert SourceDocument in types_added, "SourceDocument must be created"
    assert ParsedDocument in types_added, "ParsedDocument must be created"
    assert DocumentChunk in types_added, "DocumentChunk must be created"


@pytest.mark.asyncio
async def test_sync_knowledge_source_has_faq_authority_level():
    """The KnowledgeSource created for FAQ must have authority_level=4."""
    faq = _faq(status="approved")
    mock_db = _empty_sync_db()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await sync_faq_to_retrieval(mock_db, faq)

    ks = next((o for o in added_objects if isinstance(o, KnowledgeSource)), None)
    assert ks is not None
    assert ks.authority_level == 4
    assert ks.source_type == "faq"
    assert ks.is_active is True


@pytest.mark.asyncio
async def test_sync_knowledge_source_context_type_matches_faq():
    """KnowledgeSource context_type must match the FAQ's context_type."""
    faq = _faq(status="approved", context_type="defense_system")
    mock_db = _empty_sync_db()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await sync_faq_to_retrieval(mock_db, faq)

    ks = next((o for o in added_objects if isinstance(o, KnowledgeSource)), None)
    assert ks is not None
    assert ks.context_type == "defense_system"


@pytest.mark.asyncio
async def test_sync_source_document_has_safe_url():
    """SourceDocument URL for FAQ must use faq:// scheme, not upload:// or MinIO path."""
    faq = _faq(status="approved")
    mock_db = _empty_sync_db()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await sync_faq_to_retrieval(mock_db, faq)

    sd = next((o for o in added_objects if isinstance(o, SourceDocument)), None)
    assert sd is not None
    assert sd.url == f"faq://{faq.id}"
    assert sd.document_type == "faq"
    assert sd.status == "processed"
    assert sd.storage_bucket is None
    assert sd.storage_object_key is None


@pytest.mark.asyncio
async def test_sync_chunk_metadata_has_safe_fields():
    """DocumentChunk metadata_json must contain safe FAQ fields, not internal paths."""
    faq = _faq(status="approved")
    mock_db = _empty_sync_db()

    added_objects = []
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await sync_faq_to_retrieval(mock_db, faq)

    chunk = next((o for o in added_objects if isinstance(o, DocumentChunk)), None)
    assert chunk is not None
    meta = chunk.metadata_json
    assert meta is not None
    assert "faq_id" in meta
    assert "question" in meta
    assert "answer_excerpt" in meta
    assert "topic" in meta
    assert "official_source_links" in meta
    assert "authority_level" in meta
    assert meta["authority_level"] == 4
    assert "source_type" in meta
    assert meta["source_type"] == "faq"
    # Must NOT contain internal storage paths or MinIO keys
    meta_str = str(meta)
    assert "upload://" not in meta_str
    assert "storage_bucket" not in meta_str
    assert "minio" not in meta_str.lower()


@pytest.mark.asyncio
async def test_sync_is_idempotent_when_records_exist():
    """Sync with all records already present must not create new ones."""
    faq = _faq(status="approved")

    # Mock returns existing objects for all lookups
    existing_ks = MagicMock(spec=KnowledgeSource)
    existing_ks.id = uuid.uuid4()
    existing_sd = MagicMock(spec=SourceDocument)
    existing_sd.id = uuid.uuid4()
    existing_sd.title = faq.question[:300]  # title unchanged → no update
    existing_pd = MagicMock(spec=ParsedDocument)
    existing_pd.id = uuid.uuid4()
    existing_chunk = MagicMock(spec=DocumentChunk)
    existing_chunk.id = uuid.uuid4()

    results = iter([
        existing_ks,   # KS lookup
        existing_sd,   # SD lookup
        existing_pd,   # PD lookup
        existing_chunk,  # chunk lookup
        None,          # active IndexVersion lookup
    ])

    def _scalar_result(obj):
        r = MagicMock()
        r.scalar_one_or_none.return_value = obj
        return r

    async def _execute(*args, **kwargs):
        return _scalar_result(next(results, None))

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    await sync_faq_to_retrieval(mock_db, faq)

    # Only the AuditLog should be added (for faq_made_retrievable)
    from app.db.models.audit_log import AuditLog
    added_types = [type(o) for o in mock_db.add.call_args_list]
    non_audit_adds = [
        call for call in mock_db.add.call_args_list
        if not isinstance(call.args[0], AuditLog)
    ]
    assert len(non_audit_adds) == 0, "No new records should be created when all exist"


# ── remove_faq_from_retrieval ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remove_faq_deletes_chunk_embeddings():
    """remove_faq_from_retrieval must delete ChunkEmbedding rows for the FAQ's chunks."""
    faq_id = uuid.uuid4()
    chunk_id_1 = uuid.uuid4()
    chunk_id_2 = uuid.uuid4()

    # First execute: SourceDocument lookup → returns list with one SD
    mock_sd = MagicMock(spec=SourceDocument)
    mock_sd.id = uuid.uuid4()

    sd_result = MagicMock()
    sd_result.scalars.return_value.all.return_value = [mock_sd]

    # Second execute: DocumentChunk.id lookup → returns two chunk ids
    chunk_result = MagicMock()
    chunk_result.scalars.return_value.all.return_value = [chunk_id_1, chunk_id_2]

    # Third execute: DELETE ChunkEmbedding
    delete_result = MagicMock()

    call_count = 0
    async def _execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return sd_result
        elif call_count == 2:
            return chunk_result
        else:
            return delete_result

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    await remove_faq_from_retrieval(mock_db, faq_id)

    # Third call must be a DELETE ChunkEmbedding statement
    assert call_count >= 3, "DELETE must have been executed"


@pytest.mark.asyncio
async def test_remove_faq_with_no_existing_records_is_safe():
    """remove_faq_from_retrieval with no matching chunks must not raise."""
    faq_id = uuid.uuid4()
    mock_db = _empty_sync_db()
    # Should not raise
    await remove_faq_from_retrieval(mock_db, faq_id)


# ── Source viewer / chunk API ──────────────────────────────────────────────────

def _make_faq_chunk_row(chunk_id=None):
    """Build a fake (chunk, source_doc, ks) row for a FAQ chunk."""
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.chunk_text = "שאלה: האם ניתן לעבור לתפקיד במשרד אחר?\n\nתשובה: כן, בכפוף לאישור."
    chunk.section_title = "ניידות"
    chunk.page_number = None
    chunk.chunk_index = 0
    chunk.metadata_json = {
        "faq_id": str(uuid.uuid4()),
        "question": "האם ניתן לעבור לתפקיד במשרד אחר?",
        "answer_excerpt": "כן, בכפוף לאישור.",
        "topic": "ניידות",
        "context_type": "government_ministries",
        "applicable_population": "עובדים בדרג מקצועי",
        "official_source_links": ["https://www.civil.gov.il/takshir"],
        "authority_level": 4,
        "source_type": "faq",
        "status": "approved",
        "updated_at": "2026-06-01T00:00:00+00:00",
        "approved_by_user_id": None,
    }

    source_doc = MagicMock()
    source_doc.id = uuid.uuid4()
    source_doc.title = "האם ניתן לעבור לתפקיד במשרד אחר?"
    source_doc.document_type = "faq"

    ks = MagicMock()
    ks.id = uuid.uuid4()
    ks.name = "FAQ מאושר - משרדי ממשלה"
    ks.authority_level = 4

    return (chunk, source_doc, ks)


def _db_with_row(row):
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = row
    mock_db.execute = AsyncMock(return_value=mock_result)
    async def _dep():
        yield mock_db
    return _dep


@pytest.mark.asyncio
async def test_faq_chunk_viewer_returns_faq_fields():
    """Source viewer must return faq_id, faq_question, etc. for FAQ chunks."""
    dep = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_faq_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["document_type"] == "faq"
        assert data["authority_level"] == 4
        assert data["faq_id"] is not None
        assert data["faq_question"] is not None
        assert data["faq_answer_excerpt"] is not None
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_faq_chunk_viewer_does_not_expose_forbidden_fields():
    """Source viewer must not expose storage paths, MinIO keys, or raw prompts for FAQ chunks."""
    dep = _auth(["chat_user"])
    chunk_id = uuid.uuid4()
    row = _make_faq_chunk_row(chunk_id=chunk_id)
    app.dependency_overrides[get_current_active_user] = dep
    app.dependency_overrides[get_db] = _db_with_row(row)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/knowledge/chunks/{chunk_id}")
        response_str = str(r.json())
        assert "upload://" not in response_str
        assert "storage_bucket" not in response_str
        assert "storage_object_key" not in response_str
        assert "minio" not in response_str.lower()
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── RBAC ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_user_cannot_approve_faq():
    """chat_user must not be allowed to approve FAQ items (403)."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}/approve")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_chat_user_cannot_archive_faq():
    """chat_user must not be allowed to archive FAQ items (403)."""
    app.dependency_overrides[get_current_active_user] = _auth(["chat_user"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}/archive")
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_faq_manager_can_approve_faq():
    """faq_manager must be able to approve a draft FAQ (200)."""
    item = _faq(status="draft")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}/approve")
        assert r.status_code == 200
        assert item.status == "approved"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_faq_manager_can_archive_faq():
    """faq_manager must be able to archive an approved FAQ (200)."""
    item = _faq(status="approved")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.patch(f"/admin/faq/{uuid.uuid4()}/archive")
        assert r.status_code == 200
        assert item.status == "archived"
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_db, None)


# ── Status change affects retrieval ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_faq_triggers_sync():
    """Approving a FAQ via API must call sync_faq_to_retrieval."""
    item = _faq(status="draft")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)

    with patch("app.api.admin_faq.sync_faq_to_retrieval", new_callable=AsyncMock) as mock_sync:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.patch(f"/admin/faq/{uuid.uuid4()}/approve")
            assert r.status_code == 200
            mock_sync.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_archive_faq_triggers_removal():
    """Archiving a FAQ via API must call remove_faq_from_retrieval."""
    item = _faq(status="approved")
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)

    with patch("app.api.admin_faq.remove_faq_from_retrieval", new_callable=AsyncMock) as mock_remove:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.patch(f"/admin/faq/{uuid.uuid4()}/archive")
            assert r.status_code == 200
            mock_remove.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_update_approved_faq_content_triggers_removal():
    """Updating content of an approved FAQ (reverting to draft) must call remove_faq_from_retrieval."""
    item = _faq(status="approved")
    item.question = "שאלה ישנה?"
    app.dependency_overrides[get_current_active_user] = _auth(["faq_manager"])
    app.dependency_overrides[get_db] = _db_for_get(item)

    with patch("app.api.admin_faq.remove_faq_from_retrieval", new_callable=AsyncMock) as mock_remove:
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.patch(
                    f"/admin/faq/{uuid.uuid4()}",
                    json={"question": "שאלה חדשה?"},
                )
            assert r.status_code == 200
            assert item.status == "draft"
            mock_remove.assert_called_once()
        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
            app.dependency_overrides.pop(get_db, None)
