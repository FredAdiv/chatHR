"""Admin endpoints for processing uploaded knowledge documents.

POST /admin/knowledge/documents/{document_id}/process
  — Parse, chunk, embed, and create a draft IndexVersion for an uploaded document.
  — Does NOT activate the index. The draft must be promoted separately.

GET /admin/knowledge/documents/{document_id}
  — Return safe metadata about an uploaded SourceDocument.

Security:
- knowledge_admin or system_admin only.
- Raw file content fetched from MinIO for processing; never stored in DB, logs, or responses.
- No raw content, no request body, no stack trace exposed to callers.
- Audit log records actor, document_id, outcome, and chunk/index counts only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document_chunk import DocumentChunk
from app.db.models.index_version import IndexVersion
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.embeddings.factory import get_embedding_provider
from app.services.parsing.orchestrator import parse_and_chunk_source_document

router = APIRouter(prefix="/admin/knowledge", tags=["knowledge-process"])

_PROCESS_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

_PROCESSABLE_STATUSES = {"downloaded", "unchanged", "processed"}


# ── Response models ────────────────────────────────────────────────────────────

class DocumentStatusResponse(BaseModel):
    document_id: str
    title: str | None
    document_type: str | None
    file_format: str | None
    authority_level: int | None
    status: str
    created_at: str
    updated_at: str
    index_version_id: str | None


class ProcessResponse(BaseModel):
    document_id: str
    title: str | None
    document_type: str | None
    file_format: str | None
    authority_level: int | None
    status: str
    index_version_id: str
    index_version_label: str
    chunk_count: int
    message: str


# ── GET: document status ───────────────────────────────────────────────────────

@router.get("/documents/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_PROCESS_ROLES)),
) -> DocumentStatusResponse:
    """Return safe metadata for an uploaded SourceDocument."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid document_id format.")

    sd = await db.get(SourceDocument, doc_uuid)
    if not sd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    ks = await db.get(KnowledgeSource, sd.knowledge_source_id) if sd.knowledge_source_id else None
    authority_level = ks.authority_level if ks else None

    index_version_id: str | None = None
    if sd.metadata_json and "index_version_id" in sd.metadata_json:
        index_version_id = sd.metadata_json["index_version_id"]

    meta = sd.metadata_json or {}
    return DocumentStatusResponse(
        document_id=str(sd.id),
        title=sd.title,
        document_type=meta.get("semantic_type") or sd.document_type,
        file_format=meta.get("file_format") or sd.document_type,
        authority_level=authority_level,
        status=sd.status,
        created_at=sd.created_at.isoformat(),
        updated_at=sd.updated_at.isoformat(),
        index_version_id=index_version_id,
    )


# ── POST: process document ─────────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/process",
    status_code=status.HTTP_200_OK,
    response_model=ProcessResponse,
)
async def process_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_PROCESS_ROLES)),
) -> ProcessResponse:
    """Parse, chunk, embed, and create a draft IndexVersion for an uploaded document.

    The resulting IndexVersion has status='ready' — it is NOT activated automatically.
    A separate activation step (future endpoint) promotes it to 'active'.
    """
    now = datetime.now(timezone.utc)

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid document_id format.")

    sd = await db.get(SourceDocument, doc_uuid)
    if not sd:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if sd.status not in _PROCESSABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "wrong_status",
                "message": (
                    f"מצב המסמך הוא '{sd.status}' — לא ניתן לעבד מסמך במצב זה. "
                    f"מצבים מותרים: {', '.join(sorted(_PROCESSABLE_STATUSES))}."
                ),
            },
        )

    if not sd.storage_bucket or not sd.storage_object_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document has no MinIO storage reference. Re-upload the file first.",
        )

    ks = await db.get(KnowledgeSource, sd.knowledge_source_id) if sd.knowledge_source_id else None
    authority_level = ks.authority_level if ks else None

    start_meta = sd.metadata_json or {}
    await record_audit_event(
        db,
        action="knowledge_document_processing_started",
        actor_user_id=actor.id,
        target_type="source_document",
        target_id=str(sd.id),
        metadata_json={
            "document_type": start_meta.get("semantic_type") or sd.document_type,
            "file_format": start_meta.get("file_format") or sd.document_type,
            "authority_level": authority_level,
        },
    )
    await db.flush()

    # ── Step 1: Parse and chunk ────────────────────────────────────────────────
    try:
        parsed_doc = await parse_and_chunk_source_document(
            db, sd.id, started_by_user_id=actor.id
        )
    except Exception:
        await _audit_process_failure(db, actor, sd, "parse_error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "parse_error", "message": "שגיאה בניתוח המסמך. אנא בדוק את הלוגים."},
        )

    if parsed_doc.parse_status != "parsed":
        await _audit_process_failure(db, actor, sd, "parse_failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "parse_failed", "message": "המסמך לא ניתן לניתוח. ודא שהקובץ תקין ואינו מוגן."},
        )

    chunks = (
        await db.execute(
            select(DocumentChunk).where(DocumentChunk.parsed_document_id == parsed_doc.id)
        )
    ).scalars().all()

    if not chunks:
        await _audit_process_failure(db, actor, sd, "no_chunks")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "no_chunks", "message": "הניתוח לא הפיק תוכן. המסמך עשוי להיות ריק או לא נתמך."},
        )

    # ── Step 2: Create draft IndexVersion ─────────────────────────────────────
    provider = get_embedding_provider()
    ts = now.strftime("%Y%m%d%H%M%S")
    version_label = f"manual-upload-{str(sd.id)[:8]}-{ts}"

    iv = IndexVersion(
        version_label=version_label,
        status="building",
        embedding_model=provider.model_name,
        created_by_user_id=actor.id,
        created_at=now,
        metadata_json={
            "source_document_id": str(sd.id),
            "authority_level": authority_level,
            "document_type": sd.document_type,
            "chunk_count": len(chunks),
        },
    )
    db.add(iv)
    await db.flush()

    # ── Step 3: Generate embeddings ────────────────────────────────────────────
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
    await db.flush()

    # ── Step 4: Mark IndexVersion as draft (awaiting quality check) ───────────
    iv.status = "draft"
    await db.flush()

    # ── Step 5: Update SourceDocument status to 'processed' ───────────────────
    existing_meta = dict(sd.metadata_json or {})
    existing_meta["index_version_id"] = str(iv.id)
    existing_meta["chunk_count"] = len(chunks)
    existing_meta["processed_at"] = now.isoformat()
    sd.metadata_json = existing_meta
    sd.status = "processed"
    sd.updated_at = now
    await db.flush()

    sd_meta = sd.metadata_json or {}
    semantic_type = sd_meta.get("semantic_type") or sd.document_type
    file_format = sd_meta.get("file_format") or sd.document_type

    await record_audit_event(
        db,
        action="knowledge_document_processed",
        actor_user_id=actor.id,
        target_type="source_document",
        target_id=str(sd.id),
        metadata_json={
            "index_version_id": str(iv.id),
            "index_version_label": version_label,
            "chunk_count": len(chunks),
            "document_type": semantic_type,
            "file_format": file_format,
            "authority_level": authority_level,
            "index_status": "draft",
        },
    )
    await db.commit()

    return ProcessResponse(
        document_id=str(sd.id),
        title=sd.title,
        document_type=semantic_type,
        file_format=file_format,
        authority_level=authority_level,
        status="processed",
        index_version_id=str(iv.id),
        index_version_label=version_label,
        chunk_count=len(chunks),
        message=(
            f"המסמך עובד בהצלחה — נוצרו {len(chunks)} קטעים ואינדקס טיוטה '{version_label}'. "
            "האינדקס נמצא במצב 'draft' וממתין לבדיקות איכות לפני פרסום. "
            "לפרסום נדרש שלב בדיקות איכות ואישור נפרד."
        ),
    )


async def _audit_process_failure(
    db: AsyncSession,
    actor: User,
    sd: SourceDocument,
    error_category: str,
) -> None:
    try:
        await record_audit_event(
            db,
            action="knowledge_document_processing_failed",
            actor_user_id=actor.id,
            target_type="source_document",
            target_id=str(sd.id),
            metadata_json={"error_category": error_category, "document_type": sd.document_type},
        )
        await db.flush()
    except Exception:
        pass
