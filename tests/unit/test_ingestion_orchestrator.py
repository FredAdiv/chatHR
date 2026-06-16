"""Unit tests for the ingestion orchestration service."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.ingestion_run import IngestionRun
from app.db.models.ingestion_run_document import IngestionRunDocument
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.services.ingestion.orchestrator import run_ingestion_for_source


def _make_source(url="https://www.gov.il/docs", is_active=True):
    src = MagicMock(spec=KnowledgeSource)
    src.id = uuid.uuid4()
    src.url = url
    src.is_active = is_active
    src.name = "Test Source"
    return src


def _make_db(source=None, existing_doc=None):
    """Build a minimal async DB mock for orchestrator tests."""
    added: list = []

    async def _get(model, pk):
        if model is KnowledgeSource:
            return source
        if model is SourceDocument:
            return existing_doc
        return None

    mock_result_doc = MagicMock()
    mock_result_doc.scalar_one_or_none.return_value = existing_doc

    mock_result_audit = MagicMock()
    mock_result_audit.scalars.return_value.all.return_value = []

    async def _execute(q):
        # Return existing_doc result for SourceDocument queries, empty for audit
        return mock_result_doc

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(side_effect=_get)
    mock_db.execute = AsyncMock(side_effect=_execute)
    mock_db.add = MagicMock(side_effect=lambda x: added.append(x))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db._added = added
    return mock_db


# ── Source validation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inactive_source_raises():
    source = _make_source(is_active=False)
    db = _make_db(source=source)
    with pytest.raises(ValueError, match="inactive"):
        await run_ingestion_for_source(db, source.id, "dry_run")


@pytest.mark.asyncio
async def test_missing_source_raises():
    db = _make_db(source=None)
    with pytest.raises(ValueError, match="not found"):
        await run_ingestion_for_source(db, uuid.uuid4(), "dry_run")


# ── dry_run ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_creates_run_and_doc_without_fetching():
    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url") as mock_fetch:
        run = await run_ingestion_for_source(db, source.id, "dry_run")

    mock_fetch.assert_not_called()
    assert run.mode == "dry_run"
    assert run.status == "completed"

    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert len(run_docs) == 1
    assert run_docs[0].action == "discovered"


@pytest.mark.asyncio
async def test_dry_run_no_url_still_creates_doc():
    source = _make_source(url=None)
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url") as mock_fetch:
        run = await run_ingestion_for_source(db, source.id, "dry_run")

    mock_fetch.assert_not_called()
    assert run.status == "completed"
    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert len(run_docs) == 1
    assert run_docs[0].action == "discovered"


# ── source without URL ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_no_url_records_skipped():
    source = _make_source(url=None)
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url") as mock_fetch:
        run = await run_ingestion_for_source(db, source.id, "download")

    mock_fetch.assert_not_called()
    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert any(rd.action == "skipped" for rd in run_docs)


@pytest.mark.asyncio
async def test_metadata_only_no_url_records_skipped():
    source = _make_source(url=None)
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url") as mock_fetch:
        run = await run_ingestion_for_source(db, source.id, "metadata_only")

    mock_fetch.assert_not_called()
    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert any(rd.action == "skipped" for rd in run_docs)


# ── failed fetch ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_fetch_marks_run_failed_doc():
    from app.services.ingestion.downloader import FetchResult
    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source)

    bad_result = FetchResult(
        url="https://www.gov.il/docs",
        status_code=None,
        content_type=None,
        etag=None,
        last_modified=None,
        content=None,
        error="connection refused",
    )

    with patch("app.services.ingestion.orchestrator.fetch_url", return_value=bad_result):
        run = await run_ingestion_for_source(db, source.id, "download")

    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert any(rd.action == "failed" for rd in run_docs)
    assert run.status == "completed"  # run itself completed — the doc action is "failed"


# ── download mode — new document ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_download_computes_hash_and_stores_in_minio():
    from app.services.ingestion.downloader import FetchResult
    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source, existing_doc=None)

    content = b"<html>government content</html>"
    fetch_result = FetchResult(
        url="https://www.gov.il/docs",
        status_code=200,
        content_type="text/html",
        etag=None,
        last_modified=None,
        content=content,
        error=None,
    )

    with patch("app.services.ingestion.orchestrator.fetch_url", return_value=fetch_result), \
         patch("app.services.ingestion.orchestrator.put_bytes") as mock_put:
        run = await run_ingestion_for_source(db, source.id, "download")

    mock_put.assert_called_once()
    call_args = mock_put.call_args
    # Verify raw content was passed to MinIO helper, not stored anywhere in DB
    assert call_args.args[2] == content or call_args[0][2] == content

    source_docs = [x for x in db._added if isinstance(x, SourceDocument)]
    assert len(source_docs) == 1
    from app.services.ingestion.hash_utils import sha256_hex
    assert source_docs[0].content_hash == sha256_hex(content)

    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert any(rd.action == "downloaded" for rd in run_docs)


# ── download mode — unchanged content ────────────────────────────────────────

@pytest.mark.asyncio
async def test_unchanged_content_records_action_unchanged():
    from app.services.ingestion.downloader import FetchResult
    from app.services.ingestion.hash_utils import sha256_hex

    content = b"<html>same content</html>"
    existing = MagicMock(spec=SourceDocument)
    existing.id = uuid.uuid4()
    existing.content_hash = sha256_hex(content)
    existing.status = "downloaded"

    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source, existing_doc=existing)

    fetch_result = FetchResult(
        url="https://www.gov.il/docs",
        status_code=200,
        content_type="text/html",
        etag=None,
        last_modified=None,
        content=content,
        error=None,
    )

    with patch("app.services.ingestion.orchestrator.fetch_url", return_value=fetch_result), \
         patch("app.services.ingestion.orchestrator.put_bytes") as mock_put:
        run = await run_ingestion_for_source(db, source.id, "download")

    mock_put.assert_not_called()

    run_docs = [x for x in db._added if isinstance(x, IngestionRunDocument)]
    assert any(rd.action == "unchanged" for rd in run_docs)
    assert existing.status == "unchanged"


# ── Audit ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_records_audit_events():
    from app.db.models.audit_log import AuditLog
    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url"):
        await run_ingestion_for_source(db, source.id, "dry_run")

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    actions = {a.action for a in audit_logs}
    assert "ingestion_run_started" in actions
    assert "ingestion_run_completed" in actions


@pytest.mark.asyncio
async def test_audit_metadata_does_not_include_raw_content():
    from app.db.models.audit_log import AuditLog
    source = _make_source(url="https://www.gov.il/docs")
    db = _make_db(source=source)

    with patch("app.services.ingestion.orchestrator.fetch_url"):
        await run_ingestion_for_source(db, source.id, "dry_run")

    audit_logs = [x for x in db._added if isinstance(x, AuditLog)]
    for log in audit_logs:
        meta_str = str(log.metadata_json or {})
        assert "content" not in meta_str.lower() or "knowledge_source" in meta_str.lower()
