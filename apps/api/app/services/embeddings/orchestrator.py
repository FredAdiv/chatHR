"""Embedding generation orchestration.

Generates ChunkEmbedding records for DocumentChunk rows associated with a
building IndexVersion. All embedding calls go through embed_with_gateway().
Does not activate the index.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.services.audit import record_audit_event
from app.services.embeddings.base import EmbeddingGenerationResult
from app.services.embeddings.gateway import embed_with_gateway, get_embedding_dimension

_MUTABLE_STATUS = "building"


async def embed_chunks_for_index_version(
    db: AsyncSession,
    index_version_id: uuid.UUID,
    parsed_document_id: uuid.UUID | None = None,
    source_document_id: uuid.UUID | None = None,
    started_by_user_id: uuid.UUID | None = None,
) -> EmbeddingGenerationResult:
    """
    Generate embeddings for DocumentChunk rows and store as ChunkEmbedding records.

    - Requires IndexVersion.status == 'building'.
    - Skips chunks already embedded (same chunk + model + content_hash + index_version).
    - Does not mutate DocumentChunk rows.
    - Does not activate the IndexVersion.
    - Does not call external services (fake-local provider only in MVP).
    - Audit metadata contains counts only — no chunk text, no raw content.
    """
    now = datetime.now(timezone.utc)

    if index_version_id is None:
        raise ValueError("index_version_id is required — embeddings cannot be generated without an index version")

    index_version = await db.get(IndexVersion, index_version_id)
    if not index_version:
        raise ValueError(f"IndexVersion {index_version_id} not found")
    if index_version.status != _MUTABLE_STATUS:
        raise ValueError(
            f"IndexVersion has status '{index_version.status}' — "
            "embeddings can only be generated for 'building' index versions"
        )

    # Use the embedding config recorded on the IndexVersion, falling back to settings
    from app.core.config import settings as _settings
    emb_provider = index_version.embedding_provider or _settings.embedding_provider
    emb_model = index_version.embedding_model
    emb_dimension = index_version.embedding_dimensions or get_embedding_dimension(emb_provider)

    q = select(DocumentChunk)
    if parsed_document_id is not None:
        q = q.where(DocumentChunk.parsed_document_id == parsed_document_id)
    if source_document_id is not None:
        q = q.where(DocumentChunk.source_document_id == source_document_id)
    chunks_result = await db.execute(q)
    chunks = chunks_result.scalars().all()

    embedded_count = 0
    skipped_count = 0
    failed_count = 0

    for chunk in chunks:
        # Duplicate check: same chunk + model + content_hash + index_version
        dup_result = await db.execute(
            select(ChunkEmbedding).where(
                ChunkEmbedding.document_chunk_id == chunk.id,
                ChunkEmbedding.embedding_model == emb_model,
                ChunkEmbedding.content_hash == chunk.chunk_hash,
                ChunkEmbedding.index_version_id == index_version_id,
            )
        )
        if dup_result.scalar_one_or_none() is not None:
            skipped_count += 1
            continue

        try:
            vectors = await embed_with_gateway(
                [chunk.chunk_text],
                embedding_provider=emb_provider,
                embedding_model=emb_model,
            )
            vector = vectors[0]
            ce = ChunkEmbedding(
                id=uuid.uuid4(),
                document_chunk_id=chunk.id,
                source_document_id=chunk.source_document_id,
                parsed_document_id=chunk.parsed_document_id,
                index_version_id=index_version_id,
                embedding_model=emb_model,
                embedding_dimension=emb_dimension,
                embedding=vector,
                content_hash=chunk.chunk_hash,
                status="embedded",
                created_at=now,
                updated_at=now,
            )
            db.add(ce)
            embedded_count += 1
        except Exception as exc:
            # Record failure without storing raw chunk text in error message
            error_msg = f"{type(exc).__name__}: {str(exc)[:500]}"
            ce = ChunkEmbedding(
                id=uuid.uuid4(),
                document_chunk_id=chunk.id,
                source_document_id=chunk.source_document_id,
                parsed_document_id=chunk.parsed_document_id,
                index_version_id=index_version_id,
                embedding_model=emb_model,
                embedding_dimension=emb_dimension,
                embedding=[0.0] * emb_dimension,
                content_hash=chunk.chunk_hash,
                status="failed",
                error_message=error_msg,
                created_at=now,
                updated_at=now,
            )
            db.add(ce)
            failed_count += 1

    await db.flush()

    # Audit: counts only — never include chunk text or raw content
    await record_audit_event(
        db,
        action="embeddings_generated",
        actor_user_id=started_by_user_id,
        target_type="index_version",
        target_id=str(index_version_id),
        metadata_json={
            "embedding_provider": emb_provider,
            "embedding_model": emb_model,
            "embedding_dimension": emb_dimension,
            "chunks_found": len(chunks),
            "embedded_count": embedded_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        },
    )

    await db.commit()

    return EmbeddingGenerationResult(
        index_version_id=index_version_id,
        embedding_model=emb_model,
        embedding_dimension=emb_dimension,
        chunks_found=len(chunks),
        embedded_count=embedded_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )
