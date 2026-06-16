"""Unit tests for embed_chunks_for_index_version orchestrator."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.audit_log import AuditLog
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.services.embeddings.orchestrator import embed_chunks_for_index_version


def _make_index_version(status="building"):
    iv = MagicMock(spec=IndexVersion)
    iv.id = uuid.uuid4()
    iv.status = status
    iv.embedding_model = "fake-local-v1"
    iv.embedding_provider = "fake-local"
    iv.embedding_dimensions = 16
    return iv


def _make_chunk(chunk_text="Government policy text", chunk_hash=None):
    now = datetime.now(timezone.utc)
    chunk = MagicMock(spec=DocumentChunk)
    chunk.id = uuid.uuid4()
    chunk.parsed_document_id = uuid.uuid4()
    chunk.source_document_id = uuid.uuid4()
    chunk.chunk_text = chunk_text
    chunk.chunk_hash = chunk_hash or f"hash_{chunk_text[:10]}"
    chunk.created_at = now
    chunk.updated_at = now
    return chunk


def _make_db(index_version=None, chunks=None, existing_embedding=None):
    added: list = []

    async def _get(model, pk):
        if model is IndexVersion:
            return index_version
        return None

    mock_result_chunks = MagicMock()
    mock_result_chunks.scalars.return_value.all.return_value = chunks or []

    mock_result_dup = MagicMock()
    mock_result_dup.scalar_one_or_none.return_value = existing_embedding

    call_count = [0]

    async def _execute(stmt, *args, **kwargs):
        call_count[0] += 1
        # First execute is for chunks query, subsequent for duplicate checks
        if call_count[0] == 1:
            return mock_result_chunks
        return mock_result_dup

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=_get)
    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.add = MagicMock(side_effect=lambda x: added.append(x))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db._added = added
    return mock_db


# ── Status validation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refuses_active_index_version():
    iv = _make_index_version(status="active")
    db = _make_db(index_version=iv)
    with pytest.raises(ValueError, match="building"):
        await embed_chunks_for_index_version(db, iv.id)


@pytest.mark.asyncio
async def test_refuses_ready_index_version():
    iv = _make_index_version(status="ready")
    db = _make_db(index_version=iv)
    with pytest.raises(ValueError, match="building"):
        await embed_chunks_for_index_version(db, iv.id)


@pytest.mark.asyncio
async def test_refuses_archived_index_version():
    iv = _make_index_version(status="archived")
    db = _make_db(index_version=iv)
    with pytest.raises(ValueError, match="building"):
        await embed_chunks_for_index_version(db, iv.id)


@pytest.mark.asyncio
async def test_missing_index_version_raises():
    db = _make_db(index_version=None)
    with pytest.raises(ValueError, match="not found"):
        await embed_chunks_for_index_version(db, uuid.uuid4())


@pytest.mark.asyncio
async def test_null_index_version_id_raises():
    db = _make_db()
    with pytest.raises(ValueError, match="index_version_id is required"):
        await embed_chunks_for_index_version(db, None)


# ── Success path ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embeds_chunks_for_building_version():
    iv = _make_index_version(status="building")
    chunk = _make_chunk()
    db = _make_db(index_version=iv, chunks=[chunk])

    result = await embed_chunks_for_index_version(db, iv.id)

    assert result.chunks_found == 1
    assert result.embedded_count == 1
    assert result.skipped_count == 0
    assert result.failed_count == 0

    embeddings_added = [x for x in db._added if isinstance(x, ChunkEmbedding)]
    assert len(embeddings_added) == 1
    assert embeddings_added[0].status == "embedded"
    assert embeddings_added[0].document_chunk_id == chunk.id


# ── Duplicate skipping ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_duplicate_embeddings():
    iv = _make_index_version(status="building")
    chunk = _make_chunk()
    existing = MagicMock(spec=ChunkEmbedding)

    db = _make_db(index_version=iv, chunks=[chunk], existing_embedding=existing)

    result = await embed_chunks_for_index_version(db, iv.id)

    assert result.skipped_count == 1
    assert result.embedded_count == 0
    new_embeddings = [x for x in db._added if isinstance(x, ChunkEmbedding)]
    assert len(new_embeddings) == 0


# ── DocumentChunk not mutated ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_does_not_mutate_document_chunk():
    iv = _make_index_version(status="building")
    chunk = _make_chunk()
    original_text = chunk.chunk_text
    original_hash = chunk.chunk_hash

    db = _make_db(index_version=iv, chunks=[chunk])
    await embed_chunks_for_index_version(db, iv.id)

    assert chunk.chunk_text == original_text
    assert chunk.chunk_hash == original_hash


# ── Audit events ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_event_recorded():
    iv = _make_index_version(status="building")
    chunk = _make_chunk()
    db = _make_db(index_version=iv, chunks=[chunk])

    await embed_chunks_for_index_version(db, iv.id)

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    actions = {a.action for a in audit_logs}
    assert "embeddings_generated" in actions


@pytest.mark.asyncio
async def test_audit_metadata_contains_counts_only():
    iv = _make_index_version(status="building")
    chunk = _make_chunk(chunk_text="Sensitive HR document content")
    db = _make_db(index_version=iv, chunks=[chunk])

    await embed_chunks_for_index_version(db, iv.id)

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    gen_log = next((a for a in audit_logs if a.action == "embeddings_generated"), None)
    assert gen_log is not None
    meta_str = str(gen_log.metadata_json or {})
    assert "Sensitive HR document content" not in meta_str
    assert "chunks_found" in meta_str
    assert "embedded_count" in meta_str


# ── Provider failure ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_failure_records_failed_embedding():
    iv = _make_index_version(status="building")
    chunk = _make_chunk()
    db = _make_db(index_version=iv, chunks=[chunk])

    async def _failing_embed(texts, **kwargs):
        raise RuntimeError("simulated provider failure")

    with patch("app.services.embeddings.orchestrator.embed_with_gateway", side_effect=_failing_embed):
        result = await embed_chunks_for_index_version(db, iv.id)

    assert result.failed_count == 1
    assert result.embedded_count == 0

    failed = [x for x in db._added if isinstance(x, ChunkEmbedding)]
    assert len(failed) == 1
    assert failed[0].status == "failed"
    assert "Sensitive" not in (failed[0].error_message or "")


@pytest.mark.asyncio
async def test_provider_failure_error_message_no_chunk_text():
    iv = _make_index_version(status="building")
    chunk = _make_chunk(chunk_text="Confidential employee data")
    db = _make_db(index_version=iv, chunks=[chunk])

    async def _failing_embed(texts, **kwargs):
        raise RuntimeError("provider error")

    with patch("app.services.embeddings.orchestrator.embed_with_gateway", side_effect=_failing_embed):
        await embed_chunks_for_index_version(db, iv.id)

    failed = [x for x in db._added if isinstance(x, ChunkEmbedding)]
    assert "Confidential employee data" not in (failed[0].error_message or "")


# ── Result counts ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_contains_correct_model_info():
    iv = _make_index_version(status="building")
    db = _make_db(index_version=iv, chunks=[])

    result = await embed_chunks_for_index_version(db, iv.id)

    assert result.embedding_model == "fake-local-v1"
    assert result.embedding_dimension == 16
    assert result.chunks_found == 0
    assert result.index_version_id == iv.id
