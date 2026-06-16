"""Load a local official document file into a new active ChatHR index.

Dev/admin bridge script for local MVP testing.  Reads a local file (inside
the API container), stores raw bytes in MinIO, parses and chunks via existing
services, generates fake-local embeddings, archives any active index, and
activates the new one.  source_url is citation metadata only — never fetched.

Usage (inside the API container):
    python -m scripts.load_local_file_to_active_index "/app/local-data/takshir.pdf" \\
        --source-name "תקשי\\"ר - מסמך בדיקה מקומי" \\
        --source-url "https://www.gov.il/he/departments/policies/takshir" \\
        --context-type government_ministries \\
        --authority-level 1 \\
        --index-version "takshir-local-v1"

Security:
    Raw file content stored in MinIO only — never in DB, audit logs, or output.
    source_url is not fetched; used for citation metadata only.
    No secrets printed.  No raw document content printed.
    No internet access performed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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
from app.services.ingestion.downloader import MAX_BYTES
from app.services.ingestion.hash_utils import sha256_hex
from app.services.ingestion.storage import put_bytes
from app.services.parsing.orchestrator import parse_and_chunk_source_document

# ── Constants ──────────────────────────────────────────────────────────────────

_ALLOWED_CONTEXT_TYPES = ("government_ministries", "defense_system", "health_system")

# Maps local file extensions to document_type strings used by the parser dispatcher.
_EXT_TO_DOC_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".htm": "html",
    ".html": "html",
    ".txt": "unknown",
}

_SUPPORTED_EXTENSIONS = sorted(_EXT_TO_DOC_TYPE.keys())


# ── File validation ────────────────────────────────────────────────────────────

def validate_local_file(file_path: str) -> tuple[Path, str]:
    """Validate the local file and return (resolved_path, document_type).

    Raises ValueError with a safe message on any validation failure.
    Never prints file content.
    """
    p = Path(file_path)

    if not p.exists():
        raise ValueError(
            f"File not found: '{p.name}'. "
            "Make sure the file is mounted at the expected path inside the container."
        )
    if p.is_dir():
        raise ValueError(
            f"Path '{p.name}' is a directory, not a file. Provide a path to a document file."
        )
    if not p.is_file():
        raise ValueError(f"'{p.name}' is not a regular file.")

    try:
        size = p.stat().st_size
    except OSError as exc:
        raise ValueError(f"Cannot read file metadata for '{p.name}': {exc}") from exc

    if size == 0:
        raise ValueError(f"File '{p.name}' is empty.")
    if size > MAX_BYTES:
        raise ValueError(
            f"File '{p.name}' is {size:,} bytes, which exceeds the maximum "
            f"allowed size of {MAX_BYTES:,} bytes (20 MB)."
        )

    ext = p.suffix.lower()
    doc_type = _EXT_TO_DOC_TYPE.get(ext)
    if doc_type is None:
        raise ValueError(
            f"Unsupported file extension '{ext}'. "
            f"Supported extensions: {', '.join(_SUPPORTED_EXTENSIONS)}."
        )

    return p, doc_type


# ── MinIO storage key ──────────────────────────────────────────────────────────

def _storage_key(content_hash: str, document_type: str) -> str:
    ext_map = {"html": "html", "pdf": "pdf", "docx": "docx", "xlsx": "xlsx"}
    ext = ext_map.get(document_type, "bin")
    return f"raw/{content_hash[:2]}/{content_hash}.{ext}"


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def load_local_file(
    db: AsyncSession,
    file_path: str,
    source_name: str,
    source_url: str,
    context_type: str,
    authority_level: int,
    index_version_label: str,
) -> None:
    now = datetime.now(timezone.utc)
    provider = get_embedding_provider()

    print(f"\n[1/7] Validating local file...")
    resolved_path, document_type = validate_local_file(file_path)
    print(f"      OK — path: {resolved_path.name}  type: {document_type}")

    # ── Step 2: Read file bytes ────────────────────────────────────────────────
    print(f"[2/7] Reading file...")
    try:
        content_bytes = resolved_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Cannot read file: {exc}") from exc

    content_hash = sha256_hex(content_bytes)
    print(f"      Read {len(content_bytes):,} bytes — hash: {content_hash[:12]}...")

    # ── Step 3: Knowledge source ───────────────────────────────────────────────
    print(f"[3/7] Ensuring knowledge source...")
    ks = (
        await db.execute(
            select(KnowledgeSource).where(KnowledgeSource.name == source_name)
        )
    ).scalar_one_or_none()

    if not ks:
        ks = KnowledgeSource(
            name=source_name,
            source_type="local_file",
            url=source_url,
            authority_level=authority_level,
            is_active=True,
            context_type=context_type,
        )
        db.add(ks)
        await db.flush()
        print(f"      Created KnowledgeSource id={ks.id}")
    else:
        print(f"      Reusing KnowledgeSource id={ks.id}")

    # ── Step 4: Store in MinIO ─────────────────────────────────────────────────
    print(f"[4/7] Storing in MinIO...")
    bucket = settings.minio_bucket_documents
    object_key = _storage_key(content_hash, document_type)
    put_bytes(bucket, object_key, content_bytes, f"application/{document_type}")
    print(f"      Stored: bucket={bucket} key={object_key}")

    # ── Step 5: Source document ────────────────────────────────────────────────
    print(f"[5/7] Ensuring source document...")
    sd = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.knowledge_source_id == ks.id,
                SourceDocument.content_hash == content_hash,
            )
        )
    ).scalar_one_or_none()

    if sd:
        sd.status = "downloaded"
        sd.storage_bucket = bucket
        sd.storage_object_key = object_key
        sd.last_seen_at = now
        sd.downloaded_at = now
        await db.flush()
        print(f"      Updated SourceDocument id={sd.id}")
    else:
        sd = SourceDocument(
            knowledge_source_id=ks.id,
            url=source_url,
            title=source_name,
            document_type=document_type,
            content_hash=content_hash,
            storage_bucket=bucket,
            storage_object_key=object_key,
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

    chunks = (
        await db.execute(
            select(DocumentChunk).where(DocumentChunk.parsed_document_id == parsed_doc.id)
        )
    ).scalars().all()
    print(f"      ParsedDocument id={parsed_doc.id} — {len(chunks)} chunks")

    if not chunks:
        raise RuntimeError(
            "Parsing produced 0 chunks — document may be empty or unsupported. Index not created."
        )

    # ── Step 7: Index version, embeddings, activation ─────────────────────────
    print(f"[7/7] Creating index, generating embeddings, activating...")

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
            metadata_json={"reason": "replaced by local file load script"},
        )
    if active_versions:
        print(f"      Archived {len(active_versions)} previous active index version(s).")

    iv.status = "active"
    iv.activated_at = now
    await record_audit_event(
        db,
        action="index_version_activated",
        actor_user_id=None,
        target_type="index_version",
        target_id=str(iv.id),
        metadata_json={
            "embedding_model": provider.model_name,
            "chunk_count": embedded_count,
            "source_name": source_name,
        },
    )
    await db.commit()
    print(f"      IndexVersion activated: {effective_label}")

    # ── Success report ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("SUCCESS — local file loaded and indexed")
    print("=" * 60)
    print(f"  source_name          : {source_name}")
    print(f"  source_url (meta)    : {source_url}")
    print(f"  document_type        : {document_type}")
    print(f"  authority_level      : {authority_level}")
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
    print("  Ask a question related to the loaded document.")
    print()
    print("NOTE: LLM answers are fake-local placeholders.")
    print("      Source cards should appear with authority_level=1.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a local official document into a new active ChatHR index."
    )
    parser.add_argument("file_path", help="Absolute path to the local document file inside the container")
    parser.add_argument(
        "--source-name",
        required=True,
        help='Human-readable source name, e.g. "תקשי\\"ר - מסמך בדיקה מקומי"',
    )
    parser.add_argument(
        "--source-url",
        required=True,
        help="Citation URL for the source (not fetched; metadata only)",
    )
    parser.add_argument(
        "--context-type",
        default="government_ministries",
        choices=_ALLOWED_CONTEXT_TYPES,
        help="Knowledge context type (default: government_ministries)",
    )
    parser.add_argument(
        "--authority-level",
        type=int,
        default=1,
        help="Authority level 1-5, lower = stronger (default: 1)",
    )
    parser.add_argument(
        "--index-version",
        default="local-file-v1",
        help="Index version label (default: local-file-v1)",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    # Fail fast on file validation before connecting to DB
    try:
        validate_local_file(args.file_path)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    engine = create_async_engine(settings.async_database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            await load_local_file(
                db=db,
                file_path=args.file_path,
                source_name=args.source_name,
                source_url=args.source_url,
                context_type=args.context_type,
                authority_level=args.authority_level,
                index_version_label=args.index_version,
            )
    except RuntimeError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERROR [{type(exc).__name__}]: {str(exc)[:500]}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
