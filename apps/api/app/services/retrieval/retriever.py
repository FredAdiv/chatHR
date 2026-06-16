"""Retrieval service over ChunkEmbedding + DocumentChunk + SourceDocument + KnowledgeSource.

Query embedding is generated using the active IndexVersion's embedding provider/model,
so that queries are always compared against compatible vectors.
Query text is never stored in audit metadata.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.index_version import IndexVersion
from app.services.embeddings.gateway import embed_with_gateway
from app.services.retrieval.citation import CitationMetadata, build_citation_metadata

# Allowed context_type values matching knowledge_sources.context_type constraint
ALLOWED_CONTEXT_TYPES = frozenset({"government_ministries", "defense_system", "health_system"})

# Lower authority_level = stronger authority (tie-breaker after vector score)
# This ordering is consistent with the authority hierarchy documented in knowledge sources.
_RETRIEVAL_SQL = text("""
    SELECT
        dc.id            AS chunk_id,
        dc.chunk_text,
        dc.chunk_index,
        dc.section_title,
        dc.page_number,
        pd.id            AS parsed_document_id,
        sd.id            AS source_document_id,
        sd.url           AS source_url,
        sd.title         AS source_title,
        sd.document_type,
        ks.id            AS knowledge_source_id,
        ks.name          AS knowledge_source_name,
        ks.authority_level,
        ce.embedding <=> CAST(:query_vector AS vector) AS distance
    FROM chunk_embeddings ce
    JOIN document_chunks  dc ON dc.id = ce.document_chunk_id
    JOIN parsed_documents pd ON pd.id = ce.parsed_document_id
    JOIN source_documents sd ON sd.id = ce.source_document_id
    JOIN knowledge_sources ks ON ks.id = sd.knowledge_source_id
    WHERE ce.index_version_id = :index_version_id
      AND ce.embedding_model  = :embedding_model
      AND ce.status           = 'embedded'
    ORDER BY distance ASC, ks.authority_level ASC, dc.chunk_index ASC
    LIMIT :limit
""")

_RETRIEVAL_SQL_WITH_CONTEXT = text("""
    SELECT
        dc.id            AS chunk_id,
        dc.chunk_text,
        dc.chunk_index,
        dc.section_title,
        dc.page_number,
        pd.id            AS parsed_document_id,
        sd.id            AS source_document_id,
        sd.url           AS source_url,
        sd.title         AS source_title,
        sd.document_type,
        ks.id            AS knowledge_source_id,
        ks.name          AS knowledge_source_name,
        ks.authority_level,
        ce.embedding <=> CAST(:query_vector AS vector) AS distance
    FROM chunk_embeddings ce
    JOIN document_chunks  dc ON dc.id = ce.document_chunk_id
    JOIN parsed_documents pd ON pd.id = ce.parsed_document_id
    JOIN source_documents sd ON sd.id = ce.source_document_id
    JOIN knowledge_sources ks ON ks.id = sd.knowledge_source_id
    WHERE ce.index_version_id = :index_version_id
      AND ce.embedding_model  = :embedding_model
      AND ce.status           = 'embedded'
      AND (ks.context_type = :context_type OR ks.context_type IS NULL)
    ORDER BY distance ASC, ks.authority_level ASC, dc.chunk_index ASC
    LIMIT :limit
""")


@dataclass
class RetrievedChunk:
    chunk_id: str
    chunk_text: str
    parsed_document_id: str
    source_document_id: str
    distance: float
    score: float
    citation: CitationMetadata


async def retrieve_chunks(
    db: AsyncSession,
    query_text: str,
    index_version_id: uuid.UUID,
    context_type: str | None = None,
    limit: int = 5,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve the most relevant chunks for query_text using vector similarity.

    - Admin/debug only. Returns chunk_text and citation metadata.
    - Uses the configured embedding provider (fake-local in MVP).
    - Does NOT generate a natural language answer.
    - Does NOT call OpenRouter or any external service.
    - query_text is NOT logged or stored in audit metadata.
    - Results sorted by: cosine distance ASC, authority_level ASC, chunk_index ASC.
    - context_type filter includes sources with matching context_type OR null context_type
      (null = general source, applicable to all contexts).
    """
    if not query_text:
        raise ValueError("query_text must not be empty")
    if index_version_id is None:
        raise ValueError("index_version_id is required")
    if context_type is not None and context_type not in ALLOWED_CONTEXT_TYPES:
        raise ValueError(
            f"context_type {context_type!r} is not valid. "
            f"Allowed: {sorted(ALLOWED_CONTEXT_TYPES)}"
        )

    # Load IndexVersion to determine which embedding provider/model to use for the query.
    # The query vector MUST use the same provider+model as the stored chunk embeddings;
    # mismatched dimensions produce silently wrong similarity scores.
    iv = await db.get(IndexVersion, index_version_id)
    if iv is None:
        raise ValueError(f"IndexVersion {index_version_id} not found")

    from app.core.config import settings as _settings
    emb_provider = iv.embedding_provider or _settings.embedding_provider
    emb_model = iv.embedding_model

    query_vector = (
        await embed_with_gateway(
            [query_text],
            embedding_provider=emb_provider,
            embedding_model=emb_model,
        )
    )[0]
    vector_str = "[" + ",".join(str(f) for f in query_vector) + "]"

    params = {
        "query_vector": vector_str,
        "index_version_id": str(index_version_id),
        "embedding_model": emb_model,
        "limit": limit,
    }

    if context_type is not None:
        params["context_type"] = context_type
        stmt = _RETRIEVAL_SQL_WITH_CONTEXT
    else:
        stmt = _RETRIEVAL_SQL

    rows = await db.execute(stmt, params)

    results: list[RetrievedChunk] = []
    for row in rows:
        distance = float(row.distance)
        score = max(0.0, 1.0 - distance)

        if min_score is not None and score < min_score:
            continue

        citation = build_citation_metadata(
            chunk_index=row.chunk_index,
            section_title=row.section_title,
            page_number=row.page_number,
            source_url=row.source_url,
            source_title=row.source_title,
            document_type=row.document_type,
            knowledge_source_id=str(row.knowledge_source_id),
            knowledge_source_name=row.knowledge_source_name,
            authority_level=row.authority_level,
        )

        results.append(RetrievedChunk(
            chunk_id=str(row.chunk_id),
            chunk_text=row.chunk_text,
            parsed_document_id=str(row.parsed_document_id),
            source_document_id=str(row.source_document_id),
            distance=distance,
            score=score,
            citation=citation,
        ))

    return results
