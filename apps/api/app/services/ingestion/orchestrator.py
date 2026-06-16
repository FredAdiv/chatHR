"""Ingestion orchestration service.

MVP scope:
- Processes only the knowledge source's root URL (no recursive crawling).
- Does not parse document text, create chunks, or produce embeddings.
- Raw bytes stored only in MinIO; never in DB or audit logs.
- Supports modes: dry_run, metadata_only, download.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.ingestion_run import IngestionRun
from app.db.models.ingestion_run_document import IngestionRunDocument
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.services.audit import record_audit_event
from app.services.ingestion.document_type import detect_document_type
from app.services.ingestion.downloader import fetch_url
from app.services.ingestion.hash_utils import sha256_hex
from app.services.ingestion.storage import put_bytes
from app.services.ingestion.url_utils import validate_url

INGESTION_MODES = {"dry_run", "metadata_only", "download"}


async def run_ingestion_for_source(
    db: AsyncSession,
    source_id: uuid.UUID,
    mode: str,
    started_by_user_id: uuid.UUID | None = None,
    index_version_id: uuid.UUID | None = None,
) -> IngestionRun:
    """
    Run one ingestion cycle for a single knowledge source.

    Modes:
      dry_run       — validates source, records a run and a run-document, does not fetch.
      metadata_only — fetches HTTP headers/metadata, discovers/updates SourceDocument, no MinIO storage.
      download      — fetches full content, computes sha256, stores in MinIO if changed.

    Raises ValueError for invalid source_id or inactive source.
    Records audit events for run start and completion.
    """
    now = datetime.now(timezone.utc)

    source = await db.get(KnowledgeSource, source_id)
    if not source:
        raise ValueError(f"Knowledge source {source_id} not found")
    if not source.is_active:
        raise ValueError(f"Knowledge source {source_id} is inactive — ingestion is not allowed")

    run = IngestionRun(
        id=uuid.uuid4(),
        index_version_id=index_version_id,
        started_by_user_id=started_by_user_id,
        status="running",
        mode=mode,
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()

    await record_audit_event(
        db,
        action="ingestion_run_started",
        actor_user_id=started_by_user_id,
        target_type="ingestion_run",
        target_id=str(run.id),
        # Never include raw content, tokens, prompts, or PII in audit metadata
        metadata_json={"mode": mode, "knowledge_source_id": str(source_id)},
    )

    try:
        run_docs = await _process_source(db, run, source, mode, now)
        # Mark run failed if any document fetch failed; skipped docs keep run as completed
        failed_docs = [rd for rd in run_docs if rd.action == "failed"]
        if failed_docs:
            run.status = "failed"
            run.error_message = failed_docs[0].error_message
        else:
            run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        action_counts: dict[str, int] = {}
        for rd in run_docs:
            action_counts[rd.action] = action_counts.get(rd.action, 0) + 1
        run.summary_json = {
            "mode": mode,
            "knowledge_source_id": str(source_id),
            "documents_processed": len(run_docs),
            "actions": action_counts,
        }
    except Exception as exc:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        run.error_message = str(exc)[:2000]
        run.summary_json = {
            "mode": mode,
            "knowledge_source_id": str(source_id),
            "error": str(exc)[:500],
        }

    run.updated_at = datetime.now(timezone.utc)
    await record_audit_event(
        db,
        action="ingestion_run_completed",
        actor_user_id=started_by_user_id,
        target_type="ingestion_run",
        target_id=str(run.id),
        metadata_json={"status": run.status, "mode": mode},
    )
    await db.commit()
    return run


async def _process_source(
    db: AsyncSession,
    run: IngestionRun,
    source: KnowledgeSource,
    mode: str,
    now: datetime,
) -> list[IngestionRunDocument]:
    """Process the source's root URL. MVP only — no recursive crawling."""
    source_url = source.url
    run_docs: list[IngestionRunDocument] = []

    if not source_url and mode in ("metadata_only", "download"):
        rd = IngestionRunDocument(
            id=uuid.uuid4(),
            ingestion_run_id=run.id,
            source_document_id=None,
            url="(no url)",
            action="skipped",
            error_message="Knowledge source has no URL configured",
            created_at=now,
        )
        db.add(rd)
        await db.flush()
        run_docs.append(rd)
        return run_docs

    if mode == "dry_run":
        rd = IngestionRunDocument(
            id=uuid.uuid4(),
            ingestion_run_id=run.id,
            source_document_id=None,
            url=source_url or "(no url)",
            action="discovered",
            created_at=now,
        )
        db.add(rd)
        await db.flush()
        run_docs.append(rd)
        return run_docs

    # Validate URL before any network call
    try:
        validated_url = validate_url(source_url)
    except ValueError as exc:
        rd = IngestionRunDocument(
            id=uuid.uuid4(),
            ingestion_run_id=run.id,
            source_document_id=None,
            url=source_url or "(no url)",
            action="failed",
            error_message=str(exc),
            created_at=now,
        )
        db.add(rd)
        await db.flush()
        run_docs.append(rd)
        return run_docs

    fetch_result = await fetch_url(validated_url)

    if fetch_result.error or (
        fetch_result.status_code is not None and fetch_result.status_code >= 400
    ):
        error_msg = fetch_result.error or f"HTTP {fetch_result.status_code}"
        rd = IngestionRunDocument(
            id=uuid.uuid4(),
            ingestion_run_id=run.id,
            source_document_id=None,
            url=validated_url,
            action="failed",
            error_message=error_msg[:2000],
            created_at=now,
        )
        db.add(rd)
        await db.flush()
        run_docs.append(rd)
        return run_docs

    doc_type = detect_document_type(validated_url, fetch_result.content_type)

    result = await db.execute(
        select(SourceDocument).where(
            SourceDocument.knowledge_source_id == source.id,
            SourceDocument.url == validated_url,
        )
    )
    existing_doc = result.scalar_one_or_none()

    if mode == "metadata_only":
        if existing_doc:
            existing_doc.last_seen_at = now
            existing_doc.source_etag = fetch_result.etag
            existing_doc.source_last_modified = fetch_result.last_modified
            existing_doc.document_type = doc_type
            existing_doc.status = "discovered"
            existing_doc.updated_at = now
            sd = existing_doc
        else:
            sd = SourceDocument(
                id=uuid.uuid4(),
                knowledge_source_id=source.id,
                url=validated_url,
                document_type=doc_type,
                source_etag=fetch_result.etag,
                source_last_modified=fetch_result.last_modified,
                status="discovered",
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(sd)
        await db.flush()
        action = "discovered"

    else:  # download mode
        content = fetch_result.content or b""
        new_hash = sha256_hex(content)

        if existing_doc and existing_doc.content_hash == new_hash:
            existing_doc.last_seen_at = now
            existing_doc.source_etag = fetch_result.etag
            existing_doc.source_last_modified = fetch_result.last_modified
            existing_doc.status = "unchanged"
            existing_doc.updated_at = now
            sd = existing_doc
            action = "unchanged"
            await db.flush()
        else:
            bucket = settings.minio_bucket_documents
            object_key = f"{source.id}/{new_hash[:16]}/{doc_type}"
            # Store raw bytes only in MinIO — never in DB
            put_bytes(bucket, object_key, content, fetch_result.content_type or "application/octet-stream")

            if existing_doc:
                existing_doc.content_hash = new_hash
                existing_doc.storage_bucket = bucket
                existing_doc.storage_object_key = object_key
                existing_doc.document_type = doc_type
                existing_doc.source_etag = fetch_result.etag
                existing_doc.source_last_modified = fetch_result.last_modified
                existing_doc.status = "downloaded"
                existing_doc.downloaded_at = now
                existing_doc.last_seen_at = now
                existing_doc.updated_at = now
                sd = existing_doc
            else:
                sd = SourceDocument(
                    id=uuid.uuid4(),
                    knowledge_source_id=source.id,
                    url=validated_url,
                    document_type=doc_type,
                    source_etag=fetch_result.etag,
                    source_last_modified=fetch_result.last_modified,
                    content_hash=new_hash,
                    storage_bucket=bucket,
                    storage_object_key=object_key,
                    status="downloaded",
                    first_seen_at=now,
                    last_seen_at=now,
                    downloaded_at=now,
                    created_at=now,
                    updated_at=now,
                )
                db.add(sd)
            action = "downloaded"
            await db.flush()

    rd = IngestionRunDocument(
        id=uuid.uuid4(),
        ingestion_run_id=run.id,
        source_document_id=sd.id,
        url=validated_url,
        action=action,
        # Only safe metadata — no raw content, no prompts, no PII
        metadata_json={"document_type": doc_type, "content_type": fetch_result.content_type},
        created_at=now,
    )
    db.add(rd)
    await db.flush()
    run_docs.append(rd)
    return run_docs
