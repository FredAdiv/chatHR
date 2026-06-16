"""Parse and chunk orchestration service.

MVP scope:
- Processes a single already-downloaded SourceDocument.
- Fetches raw bytes from MinIO (never stores raw bytes in DB).
- Parses to text using the appropriate parser.
- Splits text into chunks.
- Persists ParsedDocument and DocumentChunk rows.
- Avoids duplicate ParsedDocument (same source_document + parser_name + parser_version + text_hash).
- Records audit events for parse start/success/failure.
- Does NOT create embeddings or vector data.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document_chunk import DocumentChunk
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.services.audit import record_audit_event
from app.services.chunking.chunker import chunk_text
from app.services.ingestion.hash_utils import sha256_hex
from app.services.ingestion.storage import get_bytes
from app.services.parsing.base import CURRENT_PARSER_VERSION
from app.services.parsing.dispatcher import parse_document_bytes

_DOWNLOADABLE_STATUSES = {"downloaded", "unchanged"}


async def parse_and_chunk_source_document(
    db: AsyncSession,
    source_document_id: uuid.UUID,
    parser_version: str = CURRENT_PARSER_VERSION,
    started_by_user_id: uuid.UUID | None = None,
) -> ParsedDocument:
    """
    Parse and chunk a downloaded SourceDocument.

    Raises ValueError if source_document_id not found or document not ready.
    Returns ParsedDocument (existing if same text_hash already parsed, new otherwise).
    """
    now = datetime.now(timezone.utc)

    source_doc = await db.get(SourceDocument, source_document_id)
    if not source_doc:
        raise ValueError(f"SourceDocument {source_document_id} not found")
    if source_doc.status not in _DOWNLOADABLE_STATUSES:
        raise ValueError(
            f"SourceDocument {source_document_id} has status '{source_doc.status}' — "
            "must be 'downloaded' or 'unchanged' to parse"
        )
    if not source_doc.storage_bucket or not source_doc.storage_object_key:
        raise ValueError(
            f"SourceDocument {source_document_id} has no MinIO storage reference"
        )

    await record_audit_event(
        db,
        action="document_parse_started",
        actor_user_id=started_by_user_id,
        target_type="source_document",
        target_id=str(source_document_id),
        # Never include raw content in audit metadata
        metadata_json={
            "source_document_id": str(source_document_id),
            "parser_version": parser_version,
            "document_type": source_doc.document_type,
        },
    )

    content = get_bytes(source_doc.storage_bucket, source_doc.storage_object_key)

    parse_result = parse_document_bytes(
        content,
        document_type=source_doc.document_type or "unknown",
    )

    if not parse_result.success:
        parsed_doc = ParsedDocument(
            id=uuid.uuid4(),
            source_document_id=source_document_id,
            parser_name=parse_result.parser_name,
            parser_version=parser_version,
            text_content="",
            text_hash=sha256_hex(b""),
            parse_status="failed",
            error_message=(parse_result.error or "unknown parse error")[:2000],
            metadata_json={"document_type": source_doc.document_type},
            created_at=now,
            updated_at=now,
        )
        db.add(parsed_doc)
        await db.flush()

        await record_audit_event(
            db,
            action="document_parse_failed",
            actor_user_id=started_by_user_id,
            target_type="source_document",
            target_id=str(source_document_id),
            metadata_json={
                "parser_name": parse_result.parser_name,
                "error": (parse_result.error or "")[:500],
            },
        )
        await db.commit()
        return parsed_doc

    text = parse_result.text
    text_hash = sha256_hex(text.encode("utf-8"))

    # Avoid creating duplicate ParsedDocument for same content
    result = await db.execute(
        select(ParsedDocument).where(
            ParsedDocument.source_document_id == source_document_id,
            ParsedDocument.parser_name == parse_result.parser_name,
            ParsedDocument.parser_version == parser_version,
            ParsedDocument.text_hash == text_hash,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.commit()
        return existing

    parsed_doc = ParsedDocument(
        id=uuid.uuid4(),
        source_document_id=source_document_id,
        parser_name=parse_result.parser_name,
        parser_version=parser_version,
        text_content=text,
        text_hash=text_hash,
        language=parse_result.language,
        parse_status="parsed",
        metadata_json={
            "document_type": source_doc.document_type,
            **(parse_result.metadata_json or {}),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(parsed_doc)
    await db.flush()

    chunks = chunk_text(text)
    for chunk in chunks:
        db.add(DocumentChunk(
            id=uuid.uuid4(),
            parsed_document_id=parsed_doc.id,
            source_document_id=source_document_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            chunk_hash=chunk.chunk_hash,
            token_estimate=chunk.token_estimate,
            created_at=now,
            updated_at=now,
        ))
    await db.flush()

    await record_audit_event(
        db,
        action="document_parsed_and_chunked",
        actor_user_id=started_by_user_id,
        target_type="source_document",
        target_id=str(source_document_id),
        # Never include text or raw bytes in audit metadata
        metadata_json={
            "parser_name": parse_result.parser_name,
            "chunk_count": len(chunks),
            "text_hash": text_hash,
        },
    )

    await db.commit()
    return parsed_doc
