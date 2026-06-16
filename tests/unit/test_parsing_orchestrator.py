"""Unit tests for parse_and_chunk_source_document orchestrator."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.document_chunk import DocumentChunk
from app.db.models.audit_log import AuditLog
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.services.parsing.orchestrator import parse_and_chunk_source_document


def _make_source_doc(status="downloaded", bucket="chathr-documents", key="src/abc/html"):
    now = datetime.now(timezone.utc)
    doc = MagicMock(spec=SourceDocument)
    doc.id = uuid.uuid4()
    doc.status = status
    doc.storage_bucket = bucket
    doc.storage_object_key = key
    doc.document_type = "html"
    return doc


def _make_db(source_doc=None, existing_parsed=None):
    added: list = []

    async def _get(model, pk):
        if model is SourceDocument:
            return source_doc
        if model is ParsedDocument:
            return existing_parsed
        return None

    mock_result_none = MagicMock()
    mock_result_none.scalar_one_or_none.return_value = existing_parsed

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=_get)
    mock_db.execute = AsyncMock(return_value=mock_result_none)
    mock_db.add = MagicMock(side_effect=lambda x: added.append(x))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db._added = added
    return mock_db


# ── Source validation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_source_doc_raises():
    db = _make_db(source_doc=None)
    with pytest.raises(ValueError, match="not found"):
        await parse_and_chunk_source_document(db, uuid.uuid4())


@pytest.mark.asyncio
async def test_discovered_status_raises():
    doc = _make_source_doc(status="discovered")
    db = _make_db(source_doc=doc)
    with pytest.raises(ValueError, match="status"):
        await parse_and_chunk_source_document(db, doc.id)


@pytest.mark.asyncio
async def test_missing_storage_key_raises():
    doc = _make_source_doc(key=None)
    db = _make_db(source_doc=doc)
    with pytest.raises(ValueError, match="no MinIO storage reference"):
        await parse_and_chunk_source_document(db, doc.id)


# ── Fetch from MinIO ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetches_bytes_from_storage():
    doc = _make_source_doc()
    db = _make_db(source_doc=doc)
    html_bytes = b"<html><body><p>Government info</p></body></html>"

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=html_bytes) as mock_get:
        await parse_and_chunk_source_document(db, doc.id)

    mock_get.assert_called_once_with(doc.storage_bucket, doc.storage_object_key)


# ── Parse success creates records ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_success_creates_parsed_doc_and_chunks():
    doc = _make_source_doc()
    db = _make_db(source_doc=doc)
    html_bytes = b"<html><body><p>Government info about employment law.</p></body></html>"

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=html_bytes):
        await parse_and_chunk_source_document(db, doc.id)

    parsed_docs = [x for x in db._added if isinstance(x, ParsedDocument)]
    assert len(parsed_docs) == 1
    assert parsed_docs[0].parse_status == "parsed"
    assert parsed_docs[0].text_content != ""

    chunks = [x for x in db._added if isinstance(x, DocumentChunk)]
    assert len(chunks) >= 1


# ── Parse failure records safe error ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_failure_records_failed_status():
    doc = _make_source_doc()
    doc.document_type = "pdf"
    db = _make_db(source_doc=doc)

    bad_bytes = b"this is not a pdf"

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=bad_bytes):
        result = await parse_and_chunk_source_document(db, doc.id)

    # parse_status is "failed" when parsing fails
    assert result.parse_status == "failed"
    assert result.error_message is not None
    assert len(result.error_message) <= 2000
    # No raw binary content in error message
    assert b"this is not" not in (result.error_message or "").encode("utf-8")


@pytest.mark.asyncio
async def test_parse_failure_creates_no_chunks():
    doc = _make_source_doc()
    doc.document_type = "pdf"
    db = _make_db(source_doc=doc)

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=b"not a pdf"):
        await parse_and_chunk_source_document(db, doc.id)

    chunks = [x for x in db._added if isinstance(x, DocumentChunk)]
    assert len(chunks) == 0


# ── Duplicate prevention ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_text_hash_returns_existing():
    doc = _make_source_doc()
    html_bytes = b"<html><body><p>Same content</p></body></html>"

    # Build an existing ParsedDocument that would match
    from app.services.ingestion.hash_utils import sha256_hex
    from app.services.parsing.dispatcher import parse_document_bytes
    parse_result = parse_document_bytes(html_bytes, "html")
    text_hash = sha256_hex(parse_result.text.encode("utf-8"))

    existing = MagicMock(spec=ParsedDocument)
    existing.id = uuid.uuid4()
    existing.parse_status = "parsed"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    db = _make_db(source_doc=doc)
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=html_bytes):
        result = await parse_and_chunk_source_document(db, doc.id)

    assert result is existing
    # No new ParsedDocument added
    parsed_docs = [x for x in db._added if isinstance(x, ParsedDocument)]
    assert len(parsed_docs) == 0


# ── Audit events ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_events_recorded():
    doc = _make_source_doc()
    db = _make_db(source_doc=doc)
    html_bytes = b"<html><body><p>Content</p></body></html>"

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=html_bytes):
        await parse_and_chunk_source_document(db, doc.id)

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    actions = {a.action for a in audit_logs}
    assert "document_parse_started" in actions
    assert "document_parsed_and_chunked" in actions


@pytest.mark.asyncio
async def test_audit_metadata_does_not_include_text_or_bytes():
    doc = _make_source_doc()
    db = _make_db(source_doc=doc)
    html_bytes = b"<html><body><p>Sensitive employment data</p></body></html>"

    with patch("app.services.parsing.orchestrator.get_bytes", return_value=html_bytes):
        await parse_and_chunk_source_document(db, doc.id)

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    for log in audit_logs:
        meta_str = str(log.metadata_json or {})
        assert "Sensitive employment data" not in meta_str
        assert "text_content" not in meta_str
