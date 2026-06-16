"""Knowledge chunk viewer — returns safe citation metadata for a chunk.

Authorization: chat_user or system_admin.
Does not expose MinIO object keys, storage paths, or raw document content.
Only chunk text (truncated excerpt) and safe metadata are returned.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_any_role
from app.db.models.document_chunk import DocumentChunk
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.db.session import get_db

router = APIRouter(prefix="/knowledge", tags=["knowledge-viewer"])

_VIEWER_ROLES = ["chat_user", "knowledge_admin", "system_admin"]
_EXCERPT_MAX_CHARS = 1000


class ChunkViewResponse(BaseModel):
    chunk_id: str
    source_document_id: str
    knowledge_source_id: str
    knowledge_source_name: str
    authority_level: int
    source_title: str | None
    document_type: str | None
    section_title: str | None
    page_number: int | None
    chunk_index: int
    excerpt: str
    # FAQ-specific fields — only populated when document_type='faq'
    faq_id: str | None = None
    faq_question: str | None = None
    faq_answer_excerpt: str | None = None
    faq_topic: str | None = None
    faq_applicable_population: str | None = None
    faq_official_source_links: list[str] | None = None
    faq_updated_at: str | None = None


@router.get("/chunks/{chunk_id}", response_model=ChunkViewResponse)
async def get_chunk(
    chunk_id: uuid.UUID,
    current_user=Depends(require_any_role(_VIEWER_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> ChunkViewResponse:
    """Return safe citation metadata and excerpt for a retrieved chunk.

    Accessible by chat_user, knowledge_admin, or system_admin.
    Never returns MinIO object keys, storage paths, or full document content.
    """
    result = await db.execute(
        select(DocumentChunk, SourceDocument, KnowledgeSource)
        .join(SourceDocument, DocumentChunk.source_document_id == SourceDocument.id)
        .join(KnowledgeSource, SourceDocument.knowledge_source_id == KnowledgeSource.id)
        .where(DocumentChunk.id == chunk_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")

    chunk, source_doc, ks = row

    excerpt = (chunk.chunk_text or "").strip()
    if len(excerpt) > _EXCERPT_MAX_CHARS:
        excerpt = excerpt[:_EXCERPT_MAX_CHARS] + "..."

    faq_fields: dict = {}
    if source_doc.document_type == "faq" and isinstance(chunk.metadata_json, dict):
        meta = chunk.metadata_json
        faq_fields = {
            "faq_id": meta.get("faq_id"),
            "faq_question": meta.get("question"),
            "faq_answer_excerpt": meta.get("answer_excerpt"),
            "faq_topic": meta.get("topic"),
            "faq_applicable_population": meta.get("applicable_population"),
            "faq_official_source_links": meta.get("official_source_links") or [],
            "faq_updated_at": meta.get("updated_at"),
        }

    return ChunkViewResponse(
        chunk_id=str(chunk.id),
        source_document_id=str(source_doc.id),
        knowledge_source_id=str(ks.id),
        knowledge_source_name=ks.name,
        authority_level=ks.authority_level,
        source_title=source_doc.title,
        document_type=source_doc.document_type,
        section_title=chunk.section_title,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        excerpt=excerpt,
        **faq_fields,
    )
