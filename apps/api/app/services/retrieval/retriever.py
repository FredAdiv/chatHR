"""Retrieval service over ChunkEmbedding + DocumentChunk + SourceDocument + KnowledgeSource.

Query embedding is generated using the active IndexVersion's embedding provider/model,
so that queries are always compared against compatible vectors.
Query text is never stored in audit metadata.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import operator as _operator
from functools import reduce

from sqlalchemy import case, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.knowledge_source_context import KnowledgeSourceContext
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument
from app.services.embeddings.gateway import embed_with_gateway
from app.services.retrieval.citation import CitationMetadata, build_citation_metadata
from app.services.retrieval.reranker import normalize_hebrew_text, rerank_candidates

# Allowed context_type values for chat conversations (user-selectable)
ALLOWED_CONTEXT_TYPES = frozenset({"government_ministries", "defense_system", "health_system"})

# Fetch this many candidates from vector search before lexical reranking.
# Must be >= max(limit) * CANDIDATE_MULTIPLIER to give reranking meaningful coverage.
_CANDIDATE_MULTIPLIER = 10
_MAX_CANDIDATES = 100

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
      AND (
          EXISTS (
              SELECT 1 FROM knowledge_source_contexts ksc
              WHERE ksc.knowledge_source_id = ks.id
                AND ksc.context_type IN ('general', :context_type)
          )
          OR NOT EXISTS (
              SELECT 1 FROM knowledge_source_contexts ksc2
              WHERE ksc2.knowledge_source_id = ks.id
          )
      )
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
    limit: int = 8,
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

    candidate_limit = min(limit * _CANDIDATE_MULTIPLIER, _MAX_CANDIDATES)
    params = {
        "query_vector": vector_str,
        "index_version_id": str(index_version_id),
        "embedding_model": emb_model,
        "limit": candidate_limit,
    }

    if context_type is not None:
        params["context_type"] = context_type
        stmt = _RETRIEVAL_SQL_WITH_CONTEXT
    else:
        stmt = _RETRIEVAL_SQL

    rows = await db.execute(stmt, params)

    candidates: list[RetrievedChunk] = []
    for row in rows:
        distance = float(row.distance)
        score = max(0.0, 1.0 - distance)

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

        candidates.append(RetrievedChunk(
            chunk_id=str(row.chunk_id),
            chunk_text=row.chunk_text,
            parsed_document_id=str(row.parsed_document_id),
            source_document_id=str(row.source_document_id),
            distance=distance,
            score=score,
            citation=citation,
        ))

    # Lexical reranking: combine vector distance with keyword overlap so that
    # chunks whose embeddings are diluted by mixed content but contain the
    # exact query terms are rescued from below the top-k cutoff.
    reranked = rerank_candidates(query_text, candidates)

    results: list[RetrievedChunk] = []
    for chunk in reranked[:limit]:
        if min_score is not None and chunk.score < min_score:
            continue
        results.append(chunk)

    return results


# ── Text fallback retrieval (MVP/demo only) ────────────────────────────────────

# Superset of the reranker's stop-words; also covers common Hebrew question words.
_FALLBACK_STOP_WORDS: frozenset[str] = frozenset({
    "מה", "מי", "על", "של", "את", "עם", "לפי", "לגבי", "האם",
    "הוא", "היא", "הם", "הן", "זה", "זו", "יש", "אין", "כי",
    "לא", "גם", "רק", "כל", "אנו", "אני", "אתם", "אתה", "זאת",
    "הרי", "כן", "כך", "אז", "אם", "עד", "אך", "אלה", "אלו",
    "בין", "אצל", "שם", "פה", "כאן", "שכן", "לכן",
    "בו", "בה", "לו", "לה", "להם", "להן",
    "כ", "ב", "ל", "מ", "ו", "ה", "א",
})


def _extract_fallback_terms(query: str) -> list[str]:
    """Return meaningful search terms from a Hebrew query for text-fallback retrieval.

    Uses normalize_hebrew_text (strip nikud/geresh/maqaf), removes stop words, keeps >= 3 chars.
    query_text is NOT stored or logged.
    """
    normalized = normalize_hebrew_text(query)
    tokens = normalized.split()
    return [t for t in tokens if len(t) >= 3 and t not in _FALLBACK_STOP_WORDS]


async def retrieve_chunks_text_fallback(
    db: AsyncSession,
    query_text: str,
    index_version_id: uuid.UUID,
    context_type: str | None = None,
    limit: int = 5,
) -> list[RetrievedChunk]:
    """Text-based fallback retrieval using ILIKE — MVP/demo only.

    Runs only when vector retrieval returns no results.  Uses safe parameterized
    SQLAlchemy queries (no string interpolation).  Respects active index version,
    context_type (matching OR null), and authority ordering.  Returns the same
    RetrievedChunk shape as retrieve_chunks.  query_text is NOT stored or logged.
    """
    terms = _extract_fallback_terms(query_text)
    if not terms:
        return []

    # Build per-term score expressions: exact phrase = 2 pts, each term = 1 pt.
    score_exprs = []
    stripped = query_text.strip()
    if 3 <= len(stripped) <= 80:
        score_exprs.append(case((DocumentChunk.chunk_text.ilike(f"%{stripped}%"), 2), else_=0))
    for term in terms:
        score_exprs.append(case((DocumentChunk.chunk_text.ilike(f"%{term}%"), 1), else_=0))

    text_score = reduce(_operator.add, score_exprs)

    # WHERE: phrase OR any individual term matches.
    any_conditions = [DocumentChunk.chunk_text.ilike(f"%{term}%") for term in terms]
    if 3 <= len(stripped) <= 80:
        any_conditions.append(DocumentChunk.chunk_text.ilike(f"%{stripped}%"))
    any_match = or_(*any_conditions)

    q = (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.chunk_text,
            DocumentChunk.chunk_index,
            DocumentChunk.section_title,
            DocumentChunk.page_number,
            ParsedDocument.id.label("parsed_document_id"),
            SourceDocument.id.label("source_document_id"),
            SourceDocument.url.label("source_url"),
            SourceDocument.title.label("source_title"),
            SourceDocument.document_type,
            KnowledgeSource.id.label("knowledge_source_id"),
            KnowledgeSource.name.label("knowledge_source_name"),
            KnowledgeSource.authority_level,
            text_score.label("text_score"),
        )
        .join(ParsedDocument, DocumentChunk.parsed_document_id == ParsedDocument.id)
        .join(SourceDocument, DocumentChunk.source_document_id == SourceDocument.id)
        .join(KnowledgeSource, SourceDocument.knowledge_source_id == KnowledgeSource.id)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            & (ChunkEmbedding.index_version_id == index_version_id)
            & (ChunkEmbedding.status == "embedded"),
        )
        .where(any_match)
        .order_by(
            text_score.desc(),
            KnowledgeSource.authority_level.asc(),
            DocumentChunk.chunk_index.asc(),
        )
        .limit(limit)
    )

    if context_type is not None:
        from sqlalchemy import exists as _exists
        ksc_match = _exists().where(
            (KnowledgeSourceContext.knowledge_source_id == KnowledgeSource.id)
            & KnowledgeSourceContext.context_type.in_(["general", context_type])
        )
        ksc_any = _exists().where(
            KnowledgeSourceContext.knowledge_source_id == KnowledgeSource.id
        )
        q = q.where(ksc_match | ~ksc_any)

    rows = (await db.execute(q)).all()

    results: list[RetrievedChunk] = []
    for row in rows:
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
            distance=-1.0,
            score=1.0,
            citation=citation,
        ))

    return results
