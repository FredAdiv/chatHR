"""Dev/admin diagnostic script — inspect RAG state: index versions, chunk counts, keyword search.

Usage (inside the API container):
    python -m scripts.inspect_rag_state
    python -m scripts.inspect_rag_state --query "קצובת נסיעה"
    python -m scripts.inspect_rag_state --query "נסיעה" --limit 10
    python -m scripts.inspect_rag_state --source-title "תקשי״ר"

Security:
    No secrets printed. Excerpts truncated to 300 chars. No raw full document content printed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.parsed_document import ParsedDocument
from app.db.models.source_document import SourceDocument

_EXCERPT_MAX = 300


def _truncate_excerpt(text: str) -> str:
    if len(text) <= _EXCERPT_MAX:
        return text
    return text[:_EXCERPT_MAX] + "…"


async def run_diagnostic(
    db: AsyncSession,
    query: str | None = None,
    limit: int = 10,
    source_title: str | None = None,
) -> None:
    print("\n" + "=" * 60)
    print("ChatHR RAG State Diagnostic")
    print("=" * 60)

    # ── 1. Active index versions ───────────────────────────────────────────────
    print("\n[1] Active index versions:")
    active_ivs = (
        await db.execute(
            select(IndexVersion)
            .where(IndexVersion.status == "active")
            .order_by(IndexVersion.created_at.desc())
        )
    ).scalars().all()

    if not active_ivs:
        print("  ⚠  No active index version found.")
    else:
        for iv in active_ivs:
            created = iv.created_at.strftime("%Y-%m-%d %H:%M") if iv.created_at else "—"
            activated = iv.activated_at.strftime("%Y-%m-%d %H:%M") if iv.activated_at else "—"
            meta = iv.metadata_json or {}
            print(f"  id={iv.id}  label={iv.version_label}  status={iv.status}")
            print(f"    created_at={created}  activated_at={activated}")
            print(f"    embedding_model={iv.embedding_model}")
            if meta:
                print(f"    metadata={meta}")

    # ── 2. High-level counts ───────────────────────────────────────────────────
    print("\n[2] High-level counts:")
    counts: dict[str, int] = {}
    for model, label in [
        (KnowledgeSource, "knowledge_sources"),
        (SourceDocument, "source_documents"),
        (ParsedDocument, "parsed_documents"),
        (DocumentChunk, "document_chunks"),
        (ChunkEmbedding, "chunk_embeddings"),
    ]:
        n = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        counts[label] = n
        print(f"  {label:<32} {n:>8}")

    if active_ivs:
        active_id = active_ivs[0].id
        n_embedded = (
            await db.execute(
                select(func.count()).select_from(ChunkEmbedding).where(
                    ChunkEmbedding.index_version_id == active_id,
                    ChunkEmbedding.status == "embedded",
                )
            )
        ).scalar_one()
        print(f"  {'embedded (active index)':<32} {n_embedded:>8}")
        counts["embedded_active"] = n_embedded
    else:
        counts["embedded_active"] = 0

    # ── 3. Latest knowledge sources ────────────────────────────────────────────
    print("\n[3] Latest knowledge sources (up to 10):")
    kss = (
        await db.execute(
            select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc()).limit(10)
        )
    ).scalars().all()

    if not kss:
        print("  No knowledge sources found.")
    else:
        for ks in kss:
            created = ks.created_at.strftime("%Y-%m-%d %H:%M") if ks.created_at else "—"
            print(f"  id={ks.id}")
            print(f"    name={ks.name}  authority_level={ks.authority_level}  context_type={ks.context_type or '—'}")
            print(f"    url={ks.url or '—'}  created_at={created}")

    # ── 4. Keyword text search ─────────────────────────────────────────────────
    query_rows: list = []
    if query:
        print(f"\n[4] Text search for: '{query}'  (limit={limit})")
        words = [w for w in query.split() if w]
        conditions = [DocumentChunk.chunk_text.ilike(f"%{query}%")]
        for word in words:
            conditions.append(DocumentChunk.chunk_text.ilike(f"%{word}%"))

        q = (
            select(
                DocumentChunk.id,
                DocumentChunk.chunk_index,
                DocumentChunk.chunk_text,
                DocumentChunk.section_title,
                SourceDocument.title.label("doc_title"),
                KnowledgeSource.name.label("ks_name"),
                KnowledgeSource.authority_level,
            )
            .join(SourceDocument, DocumentChunk.source_document_id == SourceDocument.id, isouter=True)
            .join(KnowledgeSource, SourceDocument.knowledge_source_id == KnowledgeSource.id, isouter=True)
            .where(or_(*conditions))
        )

        if source_title:
            q = q.where(SourceDocument.title.ilike(f"%{source_title}%"))

        q = q.limit(limit)
        query_rows = list((await db.execute(q)).all())

        if not query_rows:
            print("  No text matches found.")
        else:
            print(f"  Found {len(query_rows)} match(es):")
            for row in query_rows:
                excerpt = _truncate_excerpt(row.chunk_text)
                print(f"\n  chunk_id={row.id}  chunk_index={row.chunk_index}")
                print(f"    source={row.doc_title or '—'}  ks={row.ks_name or '—'}  authority_level={row.authority_level or '—'}")
                if row.section_title:
                    print(f"    section={row.section_title}")
                print(f"    excerpt: {excerpt}")

    # ── 5. Diagnostic guidance ─────────────────────────────────────────────────
    print("\n[Diagnostic guidance]")
    total_chunks = counts.get("document_chunks", 0)
    embedded_active = counts.get("embedded_active", 0)

    if total_chunks == 0:
        print("  ✗ No chunks → loader/parser was not run, or parsing produced 0 chunks.")
    elif query and not query_rows:
        print("  ✗ Chunks exist but no text match → wording mismatch or parser/extraction issue.")
        print("    Try shorter/different keywords or inspect the source document manually.")
    elif query and query_rows and embedded_active == 0:
        print("  ✗ Text matches found but active index has 0 embeddings → embedding step failed or was not run.")
    elif query and query_rows and embedded_active > 0:
        print("  ⚠ Text matches and embeddings exist — if chat still returns no-source,")
        print("    fake-local embeddings are not semantic; retrieval ranking may not surface these chunks.")
        print("    Switch to a real embedding provider for semantic retrieval.")

    if not active_ivs:
        print("  ✗ No active index → run load_local_file_to_active_index or activate an index version.")
    elif embedded_active == 0:
        print("  ✗ Active index has 0 embedded chunks → re-run the indexing script.")
    else:
        print(f"  ✓ Active index has {embedded_active} embedded chunk(s) — system should be able to retrieve.")

    print()


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect ChatHR RAG state: index versions, chunk counts, keyword search."
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Keyword(s) to search in chunk text (e.g. 'קצובת נסיעה')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max number of matching chunks to show (default: 10)",
    )
    parser.add_argument(
        "--source-title",
        default=None,
        help="Filter text search by source document title (ILIKE)",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    engine = create_async_engine(settings.async_database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            await run_diagnostic(
                db,
                query=args.query,
                limit=args.limit,
                source_title=args.source_title,
            )
    except Exception as exc:
        print(f"\nERROR [{type(exc).__name__}]: {str(exc)[:500]}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
