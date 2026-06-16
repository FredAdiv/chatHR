"""Admin retrieval API — debug vector search and retrieval health check.

All endpoints require knowledge_admin or system_admin.
No LLM calls. No answer generation. No external service calls.
Query text is never stored in audit metadata.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.embeddings.factory import get_embedding_provider
from app.services.retrieval.retriever import ALLOWED_CONTEXT_TYPES, retrieve_chunks

router = APIRouter(prefix="/admin/retrieval", tags=["retrieval"])

_RETRIEVAL_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

ContextType = Literal["government_ministries", "defense_system", "health_system"]


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query_text: str = Field(..., min_length=1)
    index_version_id: uuid.UUID
    context_type: ContextType | None = None
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float | None = None


class CitationResponse(BaseModel):
    source_url: str | None
    source_title: str | None
    knowledge_source_id: str
    knowledge_source_name: str
    authority_level: int
    section_title: str | None
    page_number: int | None
    chunk_index: int
    document_type: str | None


class SearchResultItem(BaseModel):
    chunk_id: str
    chunk_text: str
    parsed_document_id: str
    source_document_id: str
    distance: float
    score: float
    citation: CitationResponse


class HealthResponse(BaseModel):
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    vector_search_available: bool


# ── POST /admin/retrieval/search ──────────────────────────────────────────────

@router.post("/search", response_model=list[SearchResultItem])
async def retrieval_search(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_RETRIEVAL_ROLES)),
):
    """Admin/debug retrieval search.

    Embeds query_text using the configured provider and returns the most
    relevant chunks with citation metadata. No LLM answer is generated.
    Query text is not stored in audit metadata.
    """
    results = await retrieve_chunks(
        db=db,
        query_text=body.query_text,
        index_version_id=body.index_version_id,
        context_type=body.context_type,
        limit=body.limit,
        min_score=body.min_score,
    )

    # Audit with counts only — never include query_text
    await record_audit_event(
        db,
        action="retrieval_debug_search",
        actor_user_id=current_user.id,
        target_type="index_version",
        target_id=str(body.index_version_id),
        metadata_json={
            "result_count": len(results),
            "limit": body.limit,
            "context_type": body.context_type,
            # query_text deliberately omitted
        },
    )
    await db.commit()

    return [
        SearchResultItem(
            chunk_id=r.chunk_id,
            chunk_text=r.chunk_text,
            parsed_document_id=r.parsed_document_id,
            source_document_id=r.source_document_id,
            distance=r.distance,
            score=r.score,
            citation=CitationResponse(
                source_url=r.citation.source_url,
                source_title=r.citation.source_title,
                knowledge_source_id=r.citation.knowledge_source_id,
                knowledge_source_name=r.citation.knowledge_source_name,
                authority_level=r.citation.authority_level,
                section_title=r.citation.section_title,
                page_number=r.citation.page_number,
                chunk_index=r.citation.chunk_index,
                document_type=r.citation.document_type,
            ),
        )
        for r in results
    ]


# ── GET /admin/retrieval/health ───────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def retrieval_health(
    _current_user: User = Depends(require_any_role(_RETRIEVAL_ROLES)),
):
    """Retrieval readiness check.

    Returns provider config. Does not perform a DB query.
    vector_search_available reflects whether the configured provider is operational.
    """
    provider = get_embedding_provider()
    return HealthResponse(
        embedding_provider="fake-local",
        embedding_model=provider.model_name,
        embedding_dimension=provider.dimension,
        vector_search_available=True,
    )
