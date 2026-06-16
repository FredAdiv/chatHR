"""Admin embeddings API — generation, listing, and vector search.

All endpoints require knowledge_admin or system_admin.
No raw embedding vectors are returned by default.
Search uses the configured embedding provider (fake-local in MVP).
No external service calls are made.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.user import User
from app.db.session import get_db
from app.services.embeddings.factory import get_embedding_provider
from app.services.embeddings.orchestrator import embed_chunks_for_index_version

router = APIRouter(prefix="/admin/embeddings", tags=["embeddings"])

_EMBEDDING_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

EmbeddingStatus = Literal["embedded", "failed"]


# ── Request / Response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    index_version_id: uuid.UUID
    parsed_document_id: uuid.UUID | None = None
    source_document_id: uuid.UUID | None = None


class GenerateResponse(BaseModel):
    index_version_id: str
    embedding_model: str
    embedding_dimension: int
    chunks_found: int
    embedded_count: int
    skipped_count: int
    failed_count: int


class EmbeddingSummary(BaseModel):
    id: str
    document_chunk_id: str
    source_document_id: str
    parsed_document_id: str
    index_version_id: str | None
    embedding_model: str
    embedding_dimension: int
    content_hash: str
    status: str
    error_message: str | None
    created_at: str | None


class SearchRequest(BaseModel):
    index_version_id: uuid.UUID
    query_text: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class SearchResultItem(BaseModel):
    chunk_id: str
    chunk_text: str
    source_document_id: str
    parsed_document_id: str
    distance: float


def _to_summary(ce: ChunkEmbedding) -> EmbeddingSummary:
    return EmbeddingSummary(
        id=str(ce.id),
        document_chunk_id=str(ce.document_chunk_id),
        source_document_id=str(ce.source_document_id),
        parsed_document_id=str(ce.parsed_document_id),
        index_version_id=str(ce.index_version_id) if ce.index_version_id else None,
        embedding_model=ce.embedding_model,
        embedding_dimension=ce.embedding_dimension,
        content_hash=ce.content_hash,
        status=ce.status,
        error_message=ce.error_message,
        created_at=ce.created_at.isoformat() if ce.created_at else None,
    )


# ── POST /admin/embeddings/generate ──────────────────────────────────────────

@router.post("/generate", status_code=status.HTTP_200_OK, response_model=GenerateResponse)
async def generate_embeddings(
    body: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_EMBEDDING_ROLES)),
):
    index_version = await db.get(IndexVersion, body.index_version_id)
    if not index_version:
        raise HTTPException(status_code=404, detail="Index version not found")
    if index_version.status != "building":
        raise HTTPException(
            status_code=409,
            detail=f"Index version status is '{index_version.status}' — embeddings can only be generated for 'building' versions",
        )

    try:
        result = await embed_chunks_for_index_version(
            db=db,
            index_version_id=body.index_version_id,
            parsed_document_id=body.parsed_document_id,
            source_document_id=body.source_document_id,
            started_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return GenerateResponse(
        index_version_id=str(result.index_version_id),
        embedding_model=result.embedding_model,
        embedding_dimension=result.embedding_dimension,
        chunks_found=result.chunks_found,
        embedded_count=result.embedded_count,
        skipped_count=result.skipped_count,
        failed_count=result.failed_count,
    )


# ── GET /admin/embeddings ─────────────────────────────────────────────────────

@router.get("", response_model=list[EmbeddingSummary])
async def list_embeddings(
    index_version_id: uuid.UUID | None = Query(default=None),
    source_document_id: uuid.UUID | None = Query(default=None),
    parsed_document_id: uuid.UUID | None = Query(default=None),
    embedding_model: str | None = Query(default=None),
    embedding_status: EmbeddingStatus | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_EMBEDDING_ROLES)),
):
    q = select(ChunkEmbedding)
    if index_version_id is not None:
        q = q.where(ChunkEmbedding.index_version_id == index_version_id)
    if source_document_id is not None:
        q = q.where(ChunkEmbedding.source_document_id == source_document_id)
    if parsed_document_id is not None:
        q = q.where(ChunkEmbedding.parsed_document_id == parsed_document_id)
    if embedding_model is not None:
        q = q.where(ChunkEmbedding.embedding_model == embedding_model)
    if embedding_status is not None:
        q = q.where(ChunkEmbedding.status == embedding_status)
    result = await db.execute(q)
    return [_to_summary(ce) for ce in result.scalars().all()]


# ── POST /admin/embeddings/search ─────────────────────────────────────────────

@router.post("/search", response_model=list[SearchResultItem])
async def search_embeddings(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_any_role(_EMBEDDING_ROLES)),
):
    """Admin/debug vector similarity search.

    Embeds query_text using the configured provider (fake-local in MVP),
    then returns the top chunks by cosine distance.
    No external service calls are made.
    Raw embedding vectors are not returned.
    """
    provider = get_embedding_provider()
    query_vector = provider.embed_texts([body.query_text])[0]

    # pgvector cosine distance via raw SQL for maximum compatibility
    stmt = text("""
        SELECT
            ce.id            AS id,
            ce.source_document_id,
            ce.parsed_document_id,
            dc.chunk_text,
            ce.embedding <=> CAST(:query_vector AS vector) AS distance
        FROM chunk_embeddings ce
        JOIN document_chunks dc ON dc.id = ce.document_chunk_id
        WHERE ce.index_version_id = :index_version_id
          AND ce.embedding_model   = :embedding_model
          AND ce.status            = 'embedded'
        ORDER BY ce.embedding <=> CAST(:query_vector AS vector)
        LIMIT :limit
    """)

    vector_str = "[" + ",".join(str(f) for f in query_vector) + "]"
    rows = await db.execute(
        stmt,
        {
            "query_vector": vector_str,
            "index_version_id": str(body.index_version_id),
            "embedding_model": provider.model_name,
            "limit": body.limit,
        },
    )

    return [
        SearchResultItem(
            chunk_id=str(row.id),
            chunk_text=row.chunk_text,
            source_document_id=str(row.source_document_id),
            parsed_document_id=str(row.parsed_document_id),
            distance=float(row.distance),
        )
        for row in rows
    ]
