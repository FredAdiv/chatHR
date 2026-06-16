"""FAQ retrieval sync — manages DocumentChunk/ChunkEmbedding records for approved FAQs.

When a FAQ is approved, this service creates/updates its retrievable representation
so the chat RAG pipeline can find it. When a FAQ is archived or reverted to draft,
this service removes its ChunkEmbedding records (making it un-retrievable).

Representation in DB:
  KnowledgeSource (authority_level=4, source_type='faq', context_type matches FAQ)
  └─ SourceDocument (url='faq://{faq_id}', document_type='faq', no MinIO storage)
     └─ ParsedDocument (parser_name='faq-sync', text_content = Q + A)
        └─ DocumentChunk (chunk_text = Q + A, metadata_json = safe FAQ fields)
           └─ ChunkEmbedding (for each active IndexVersion)

Draft and archived FAQ items must never appear in retrieval results.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.faq_item import FaqItem
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.services.audit import record_audit_event
from app.services.embeddings.factory import get_embedding_provider

log = logging.getLogger(__name__)

_FAQ_SOURCE_TYPE = "faq"
_FAQ_AUTHORITY_LEVEL = 4
_FAQ_PARSER_NAME = "faq-sync"
_FAQ_PARSER_VERSION = "1"


def _faq_chunk_text(faq: FaqItem) -> str:
    return f"שאלה: {faq.question}\n\nתשובה: {faq.answer}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _get_or_create_faq_knowledge_source(
    db: AsyncSession,
    context_type: str | None,
) -> KnowledgeSource:
    """Get or create the singleton FAQ KnowledgeSource for a given context_type.

    One KnowledgeSource is created per distinct context_type value (including None).
    This maps to the retrieval SQL: context_type = :context_type OR context_type IS NULL.
    """
    result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.source_type == _FAQ_SOURCE_TYPE,
            KnowledgeSource.context_type == context_type,
            KnowledgeSource.authority_level == _FAQ_AUTHORITY_LEVEL,
        )
    )
    ks = result.scalar_one_or_none()
    if ks is not None:
        return ks

    _context_names: dict[str | None, str] = {
        None: "FAQ מאושר",
        "government_ministries": "FAQ מאושר - משרדי ממשלה",
        "defense_system": "FAQ מאושר - מערכת הביטחון",
        "health_system": "FAQ מאושר - מערכת הבריאות",
    }
    ks = KnowledgeSource(
        id=uuid.uuid4(),
        name=_context_names.get(context_type, f"FAQ מאושר - {context_type}"),
        source_type=_FAQ_SOURCE_TYPE,
        authority_level=_FAQ_AUTHORITY_LEVEL,
        is_active=True,
        context_type=context_type,
    )
    db.add(ks)
    await db.flush()
    return ks


async def _get_or_create_faq_source_document(
    db: AsyncSession,
    ks: KnowledgeSource,
    faq: FaqItem,
) -> SourceDocument:
    faq_url = f"faq://{faq.id}"
    result = await db.execute(
        select(SourceDocument).where(
            SourceDocument.knowledge_source_id == ks.id,
            SourceDocument.url == faq_url,
        )
    )
    sd = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if sd is not None:
        new_title = faq.question[:300]
        if sd.title != new_title:
            sd.title = new_title
            sd.updated_at = now
        return sd

    sd = SourceDocument(
        id=uuid.uuid4(),
        knowledge_source_id=ks.id,
        url=faq_url,
        title=faq.question[:300],
        document_type="faq",
        status="processed",
        first_seen_at=now,
        last_seen_at=now,
        # No storage_bucket / storage_object_key — FAQ is not stored in MinIO
    )
    db.add(sd)
    await db.flush()
    return sd


async def _get_or_create_faq_parsed_document(
    db: AsyncSession,
    sd: SourceDocument,
    faq: FaqItem,
) -> ParsedDocument:
    text_content = _faq_chunk_text(faq)
    text_hash = _sha256(text_content)

    result = await db.execute(
        select(ParsedDocument).where(
            ParsedDocument.source_document_id == sd.id,
            ParsedDocument.parser_name == _FAQ_PARSER_NAME,
            ParsedDocument.parser_version == _FAQ_PARSER_VERSION,
            ParsedDocument.text_hash == text_hash,
        )
    )
    pd = result.scalar_one_or_none()
    if pd is not None:
        return pd

    pd = ParsedDocument(
        id=uuid.uuid4(),
        source_document_id=sd.id,
        parser_name=_FAQ_PARSER_NAME,
        parser_version=_FAQ_PARSER_VERSION,
        text_content=text_content,
        text_hash=text_hash,
        language="he",
        parse_status="parsed",
    )
    db.add(pd)
    await db.flush()
    return pd


async def _get_or_create_faq_chunk(
    db: AsyncSession,
    pd: ParsedDocument,
    sd: SourceDocument,
    faq: FaqItem,
) -> DocumentChunk:
    result = await db.execute(
        select(DocumentChunk).where(
            DocumentChunk.parsed_document_id == pd.id,
            DocumentChunk.chunk_index == 0,
        )
    )
    chunk = result.scalar_one_or_none()
    if chunk is not None:
        return chunk

    chunk_text = _faq_chunk_text(faq)
    metadata = {
        "faq_id": str(faq.id),
        "question": faq.question,
        "answer_excerpt": faq.answer[:500] if faq.answer else None,
        "topic": faq.topic,
        "context_type": faq.context_type,
        "applicable_population": faq.applicable_population,
        "official_source_links": faq.official_source_links or [],
        "authority_level": _FAQ_AUTHORITY_LEVEL,
        "source_type": _FAQ_SOURCE_TYPE,
        "status": faq.status,
        "updated_at": faq.updated_at.isoformat() if faq.updated_at else None,
        "approved_by_user_id": str(faq.approved_by_user_id) if faq.approved_by_user_id else None,
    }
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        parsed_document_id=pd.id,
        source_document_id=sd.id,
        chunk_index=0,
        chunk_text=chunk_text,
        chunk_hash=_sha256(chunk_text),
        section_title=faq.topic,
        page_number=None,
        token_estimate=len(chunk_text) // 4,
        metadata_json=metadata,
    )
    db.add(chunk)
    await db.flush()
    return chunk


async def _embed_chunk_for_active_index(
    db: AsyncSession,
    chunk: DocumentChunk,
    sd: SourceDocument,
    pd: ParsedDocument,
) -> None:
    """Embed a FAQ chunk for the currently active IndexVersion (best-effort).

    If no active index exists, or if embedding fails, this is a no-op.
    The chunk will be embedded during the next index build automatically.
    """
    iv_result = await db.execute(
        select(IndexVersion).where(IndexVersion.status == "active")
    )
    active_iv = iv_result.scalar_one_or_none()
    if active_iv is None:
        return

    try:
        provider = get_embedding_provider()
        content_hash = chunk.chunk_hash

        existing = await db.execute(
            select(ChunkEmbedding).where(
                ChunkEmbedding.document_chunk_id == chunk.id,
                ChunkEmbedding.embedding_model == provider.model_name,
                ChunkEmbedding.content_hash == content_hash,
                ChunkEmbedding.index_version_id == active_iv.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return

        vectors = provider.embed_texts([chunk.chunk_text])
        vector = vectors[0]
        ce = ChunkEmbedding(
            id=uuid.uuid4(),
            document_chunk_id=chunk.id,
            source_document_id=sd.id,
            parsed_document_id=pd.id,
            index_version_id=active_iv.id,
            embedding_model=provider.model_name,
            embedding_dimension=len(vector),
            embedding=vector,
            content_hash=content_hash,
            status="embedded",
        )
        db.add(ce)
        await db.flush()
    except Exception:
        log.exception(
            "FAQ embedding failed for faq_chunk=%s — chunk will be embedded during next index build",
            chunk.id,
        )


async def sync_faq_to_retrieval(
    db: AsyncSession,
    faq: FaqItem,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Sync an approved FAQ item into the retrieval pipeline.

    Idempotent: safe to call multiple times. Only approved FAQs are synced;
    draft or archived FAQs are silently skipped.

    Creates/updates:
    - KnowledgeSource (authority_level=4, source_type='faq')
    - SourceDocument (url=faq://{faq_id}, document_type='faq', no MinIO)
    - ParsedDocument (Q+A text)
    - DocumentChunk (Q+A text, FAQ metadata)
    - ChunkEmbedding for currently active IndexVersion (best-effort)
    """
    if faq.status != "approved":
        return

    ks = await _get_or_create_faq_knowledge_source(db, faq.context_type)
    sd = await _get_or_create_faq_source_document(db, ks, faq)
    pd = await _get_or_create_faq_parsed_document(db, sd, faq)
    chunk = await _get_or_create_faq_chunk(db, pd, sd, faq)

    await _embed_chunk_for_active_index(db, chunk, sd, pd)

    await record_audit_event(
        db,
        action="faq_made_retrievable",
        actor_user_id=actor_user_id,
        target_type="faq_item",
        target_id=str(faq.id),
        metadata_json={"faq_id": str(faq.id)},
    )


async def remove_faq_from_retrieval(
    db: AsyncSession,
    faq_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Remove a FAQ item from the retrieval pipeline.

    Deletes all ChunkEmbedding records for the FAQ's DocumentChunks, so the FAQ
    is no longer returned by retrieval queries. DocumentChunk rows are kept for
    historical reference (they will be excluded because no active ChunkEmbedding
    exists for them).
    """
    sd_result = await db.execute(
        select(SourceDocument).where(SourceDocument.url == f"faq://{faq_id}")
    )
    source_docs = sd_result.scalars().all()

    chunk_ids: list[uuid.UUID] = []
    for sd in source_docs:
        chunk_result = await db.execute(
            select(DocumentChunk.id).where(DocumentChunk.source_document_id == sd.id)
        )
        chunk_ids.extend(chunk_result.scalars().all())

    if chunk_ids:
        await db.execute(
            delete(ChunkEmbedding).where(ChunkEmbedding.document_chunk_id.in_(chunk_ids))
        )

    await record_audit_event(
        db,
        action="faq_removed_from_retrieval",
        actor_user_id=actor_user_id,
        target_type="faq_item",
        target_id=str(faq_id),
        metadata_json={"faq_id": str(faq_id), "chunks_affected": len(chunk_ids)},
    )
