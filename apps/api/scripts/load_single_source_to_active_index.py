"""Load a single official gov.il URL into a new active index.

Dev/admin bridge script — fetches one URL, parses, chunks, embeds with
fake-local provider, and activates a new index version.  Any previously
active index is archived.  Not a full crawler; not a production admin UI.

Usage (inside the API container):
    python -m scripts.load_single_source_to_active_index "https://www.gov.il/he/..."

Optional flags:
    --context-type   government_ministries | defense_system | health_system  [default: government_ministries]
    --authority-level  1-5  [default: 3]
    --source-name    "Human-readable name"  [default: derived from URL]
    --index-version  version_label string  [default: manual-local-v1]

Security:
    Only gov.il URLs are accepted.
    SSRF protections from url_utils.validate_url apply inside the downloader.
    Raw document bytes stored in MinIO — never in DB or logs.
    No secrets printed.  No raw content printed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.services.audit import record_audit_event
from app.services.embeddings.factory import get_embedding_provider
from app.services.ingestion.document_type import detect_document_type
from app.services.ingestion.downloader import fetch_url
from app.services.ingestion.hash_utils import sha256_hex
from app.services.ingestion.storage import put_bytes
from app.services.ingestion.url_utils import validate_url
from app.services.parsing.orchestrator import parse_and_chunk_source_document

# ── Constants ──────────────────────────────────────────────────────────────────

_ALLOWED_CONTEXT_TYPES = ("government_ministries", "defense_system", "health_system")
_GOV_IL_SUFFIX = ".gov.il"


# ── URL validation ─────────────────────────────────────────────────────────────

def validate_gov_il_url(url: str) -> str:
    """Validate URL passes SSRF checks and is a gov.il domain.

    Returns the validated URL or raises ValueError with a safe message.
    Does not print or log the URL contents.
    """
    validated = validate_url(url)  # SSRF / scheme check
    host = urlparse(validated).hostname or ""
    if not (host == "gov.il" or host.endswith(_GOV_IL_SUFFIX)):
        raise ValueError(
            f"Only official gov.il URLs are accepted by this script. "
            f"Received host: '{host}'. "
            "To load non-official sources, use the admin API directly."
        )
    return validated


# ── MinIO storage key ──────────────────────────────────────────────────────────

def _storage_key(content_hash: str, document_type: str) -> str:
    ext_map = {"html": "html", "pdf": "pdf", "docx": "docx", "xlsx": "xlsx"}
    ext = ext_map.get(document_type, "bin")
    return f"raw/{content_hash[:2]}/{content_hash}.{ext}"


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def load_source(
    db: AsyncSession,
    url: str,
    context_type: str,
    authority_level: int,
    source_name: str | None,
    index_version_label: str,
) -> None:
    now = datetime.now(timezone.utc)
    provider = get_embedding_provider()

    print(f"\n[1/7] Validating URL...")
    validated_url = validate_gov_il_url(url)
    print(f"      OK — host: {urlparse(validated_url).hostname}")

    # ── Step 2: Knowledge source ───────────────────────────────────────────────
    print(f"[2/7] Ensuring knowledge source...")
    ks = (
        await db.execute(
            select(KnowledgeSource).where(KnowledgeSource.url == validated_url)
        )
    ).scalar_one_or_none()

    if not ks:
        name = source_name or f"Official source: {urlparse(validated_url).path.rstrip('/') or validated_url}"
        ks = KnowledgeSource(
            name=name,
            source_type="web",
            url=validated_url,
            authority_level=authority_level,
            is_active=True,
            context_type=context_type,
        )
        db.add(ks)
        await db.flush()
        print(f"      Created KnowledgeSource id={ks.id}")
    else:
        print(f"      Reusing KnowledgeSource id={ks.id}")

    # ── Step 3: Download ───────────────────────────────────────────────────────
    print(f"[3/7] Downloading URL...")
    fetch_result = await fetch_url(validated_url)
    if fetch_result.error or not fetch_result.content:
        raise RuntimeError(
            f"Download failed at stage 'fetch': {fetch_result.error or 'no content received'}"
        )
    if fetch_result.status_code and fetch_result.status_code >= 400:
        raise RuntimeError(
            f"Download failed: HTTP {fetch_result.status_code}"
        )

    content_bytes = fetch_result.content
    content_hash = sha256_hex(content_bytes)
    document_type = detect_document_type(validated_url, fetch_result.content_type)
    print(f"      Downloaded {len(content_bytes):,} bytes — type={document_type} hash={content_hash[:12]}...")

    # ── Step 4: Store in MinIO ─────────────────────────────────────────────────
    print(f"[4/7] Storing in MinIO...")
    bucket = settings.minio_bucket_documents
    object_key = _storage_key(content_hash, document_type)
    put_bytes(bucket, object_key, content_bytes, fetch_result.content_type or "application/octet-stream")
    print(f"      Stored: bucket={bucket} key={object_key}")

    # ── Step 5: Source document ────────────────────────────────────────────────
    print(f"[5/7] Ensuring source document...")
    sd = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.knowledge_source_id == ks.id,
                SourceDocument.url == validated_url,
            )
        )
    ).scalar_one_or_none()

    if sd:
        # Update existing record with fresh download info
        sd.status = "downloaded"
        sd.content_hash = content_hash
        sd.document_type = document_type
        sd.storage_bucket = bucket
        sd.storage_object_key = object_key
        sd.source_etag = fetch_result.etag
        sd.source_last_modified = fetch_result.last_modified
        sd.last_seen_at = now
        sd.downloaded_at = now
        await db.flush()
        print(f"      Updated SourceDocument id={sd.id}")
    else:
        # Derive a title from the URL path
        path_parts = [p for p in urlparse(validated_url).path.split("/") if p]
        title = path_parts[-1].replace("-", " ").replace("_", " ").title() if path_parts else None
        sd = SourceDocument(
            knowledge_source_id=ks.id,
            url=validated_url,
            title=title,
            document_type=document_type,
            content_hash=content_hash,
            storage_bucket=bucket,
            storage_object_key=object_key,
            source_etag=fetch_result.etag,
            source_last_modified=fetch_result.last_modified,
            status="downloaded",
            first_seen_at=now,
            last_seen_at=now,
            downloaded_at=now,
        )
        db.add(sd)
        await db.flush()
        print(f"      Created SourceDocument id={sd.id}")

    await db.commit()

    # ── Step 6: Parse and chunk ────────────────────────────────────────────────
    print(f"[6/7] Parsing and chunking...")
    parsed_doc = await parse_and_chunk_source_document(db, sd.id)
    if parsed_doc.parse_status != "parsed":
        raise RuntimeError(
            f"Parsing failed at stage 'parse': {parsed_doc.error_message or 'unknown error'}"
        )

    chunk_count = (
        await db.execute(
            select(DocumentChunk).where(DocumentChunk.parsed_document_id == parsed_doc.id)
        )
    )
    chunks = chunk_count.scalars().all()
    print(f"      ParsedDocument id={parsed_doc.id} — {len(chunks)} chunks")

    if not chunks:
        raise RuntimeError(
            "Parsing produced 0 chunks — document may be empty or unparseable. Index not created."
        )

    # ── Step 7: Index version, embeddings, activation ─────────────────────────
    print(f"[7/7] Creating index, generating embeddings, activating...")

    # Create a new building index (always new per run, per instructions)
    # If the label already exists, append a timestamp to avoid unique constraint violation
    existing_label = (
        await db.execute(
            select(IndexVersion).where(IndexVersion.version_label == index_version_label)
        )
    ).scalar_one_or_none()

    if existing_label:
        ts = now.strftime("%Y%m%d%H%M%S")
        effective_label = f"{index_version_label}-{ts}"
        print(f"      Label '{index_version_label}' taken — using '{effective_label}'")
    else:
        effective_label = index_version_label

    iv = IndexVersion(
        version_label=effective_label,
        status="building",
        embedding_model=provider.model_name,
        created_at=now,
    )
    db.add(iv)
    await db.flush()
    print(f"      IndexVersion id={iv.id} label={effective_label} status=building")

    # Generate embeddings for the parsed document's chunks
    embedded_count = 0
    for chunk in chunks:
        vector = provider.embed_texts([chunk.chunk_text])[0]
        db.add(ChunkEmbedding(
            document_chunk_id=chunk.id,
            source_document_id=chunk.source_document_id,
            parsed_document_id=chunk.parsed_document_id,
            index_version_id=iv.id,
            embedding_model=provider.model_name,
            embedding_dimension=provider.dimension,
            embedding=vector,
            content_hash=chunk.chunk_hash,
            status="embedded",
            created_at=now,
            updated_at=now,
        ))
        embedded_count += 1
    await db.flush()
    print(f"      Generated {embedded_count} fake-local embeddings.")

    # Archive any currently active index version(s)
    active_versions = (
        await db.execute(select(IndexVersion).where(IndexVersion.status == "active"))
    ).scalars().all()
    for old_iv in active_versions:
        old_iv.status = "archived"
        await record_audit_event(
            db,
            action="index_version_archived",
            actor_user_id=None,
            target_type="index_version",
            target_id=str(old_iv.id),
            metadata_json={"reason": "replaced by new index via load_single_source script"},
        )
    if active_versions:
        print(f"      Archived {len(active_versions)} previous active index version(s).")

    # Activate the new index
    iv.status = "active"
    iv.activated_at = now
    await record_audit_event(
        db,
        action="index_version_activated",
        actor_user_id=None,
        target_type="index_version",
        target_id=str(iv.id),
        metadata_json={"embedding_model": provider.model_name, "chunk_count": embedded_count},
    )
    await db.commit()
    print(f"      IndexVersion activated: {effective_label}")

    # ── Success report ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("SUCCESS — single source loaded and indexed")
    print("=" * 60)
    print(f"  knowledge_source_id  : {ks.id}")
    print(f"  source_document_id   : {sd.id}")
    print(f"  parsed_document_id   : {parsed_doc.id}")
    print(f"  chunk_count          : {len(chunks)}")
    print(f"  embedding_count      : {embedded_count}")
    print(f"  index_version_id     : {iv.id}")
    print(f"  index_version_label  : {effective_label}")
    print(f"  active status        : {iv.status}")
    print()
    print("Manual test:")
    print("  Login: chat@example.com / chat_dev_password")
    print("  Context: government_ministries")
    print("  Ask a question related to the loaded source.")
    print()
    print("NOTE: LLM answers are fake-local placeholders.")
    print("      Source cards should appear referencing this source.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a single official gov.il URL into a new active ChatHR index."
    )
    parser.add_argument("url", help="gov.il URL to fetch and index")
    parser.add_argument(
        "--context-type",
        default="government_ministries",
        choices=_ALLOWED_CONTEXT_TYPES,
        help="Knowledge context type (default: government_ministries)",
    )
    parser.add_argument(
        "--authority-level",
        type=int,
        default=3,
        help="Authority level 1-5, lower = stronger (default: 3)",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="Human-readable source name (default: derived from URL)",
    )
    parser.add_argument(
        "--index-version",
        default="manual-local-v1",
        help="Index version label (default: manual-local-v1)",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    # Validate URL early so we fail fast before connecting to DB
    try:
        validate_gov_il_url(args.url)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    engine = create_async_engine(settings.async_database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            await load_source(
                db=db,
                url=args.url,
                context_type=args.context_type,
                authority_level=args.authority_level,
                source_name=args.source_name,
                index_version_label=args.index_version,
            )
    except RuntimeError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
    except Exception as exc:
        # Safety net — print type only, not potentially sensitive content
        print(f"\nERROR [{type(exc).__name__}]: {str(exc)[:500]}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
