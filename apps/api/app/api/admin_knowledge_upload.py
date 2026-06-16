"""Admin endpoint for manual document upload into the knowledge base.

Security:
- Only knowledge_admin or system_admin roles may access this endpoint.
- Raw file content is stored in MinIO only — never in DB, audit logs, or responses.
- No raw content logged anywhere. No stack traces exposed to callers.
- Filename validated by extension — MIME type is not trusted alone.
- Audit log records actor, filename (safe), document_type, authority_level, and outcome.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.config import settings
from app.core.roles import RoleName
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.source_document import SourceDocument
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.ingestion.downloader import MAX_BYTES
from app.services.ingestion.hash_utils import sha256_hex
from app.services.ingestion.storage import put_bytes

router = APIRouter(prefix="/admin/knowledge", tags=["knowledge-upload"])

_UPLOAD_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

_EXT_TO_FORMAT: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".htm": "html",
    ".html": "html",
    ".txt": "unknown",
}

_SUPPORTED_EXTENSIONS = sorted(_EXT_TO_FORMAT.keys())


# ── Response model ─────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    document_id: str
    knowledge_source_id: str
    status: str
    message: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_extension(filename: str) -> str:
    """Return the document format string, or raise HTTPException 422."""
    ext = PurePosixPath(filename.lower()).suffix
    fmt = _EXT_TO_FORMAT.get(ext)
    if fmt is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "unsupported_extension",
                "message": f"סיומת הקובץ '{ext}' אינה נתמכת. "
                           f"סיומות נתמכות: {', '.join(_SUPPORTED_EXTENSIONS)}.",
            },
        )
    return fmt


def _storage_key(content_hash: str, file_format: str) -> str:
    ext_map = {"html": "html", "pdf": "pdf", "docx": "docx", "xlsx": "xlsx"}
    ext = ext_map.get(file_format, "bin")
    return f"raw/{content_hash[:2]}/{content_hash}.{ext}"


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=UploadResponse)
async def upload_document(
    file: Annotated[UploadFile, File(description="Document file to upload")],
    title: Annotated[str, Form(description="Human-readable document title")],
    document_type: Annotated[str, Form(description="Semantic document type, e.g. 'takshir'")],
    authority_level: Annotated[int, Form(description="Authority level 1-5 (lower = stronger)")],
    source_url: Annotated[str | None, Form(description="Citation URL (not fetched)")] = None,
    system_context: Annotated[str | None, Form(description="System context (optional)")] = None,
    notes: Annotated[str | None, Form(description="Admin notes (optional)")] = None,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_UPLOAD_ROLES)),
) -> UploadResponse:
    """Upload a document into the knowledge base (manual admin ingestion)."""
    now = datetime.now(timezone.utc)

    # ── Input validation ───────────────────────────────────────────────────────
    if not title or not title.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "missing_title", "message": "שדה 'כותרת' הוא חובה."},
        )

    if not document_type or not document_type.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "missing_document_type", "message": "שדה 'סוג מסמך' הוא חובה."},
        )

    if authority_level < 1 or authority_level > 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_authority_level", "message": "רמת הסמכות חייבת להיות בין 1 ל-5."},
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "missing_filename", "message": "לא סופק שם קובץ."},
        )

    safe_filename = PurePosixPath(file.filename).name
    file_format = _validate_extension(safe_filename)

    # ── Read file content ──────────────────────────────────────────────────────
    try:
        content_bytes = await file.read()
    except Exception:
        await _audit_failure(db, actor, safe_filename, document_type, authority_level, "read_error")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "read_error", "message": "לא ניתן לקרוא את הקובץ."},
        )

    if len(content_bytes) == 0:
        await _audit_failure(db, actor, safe_filename, document_type, authority_level, "empty_file")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "empty_file", "message": "הקובץ שהועלה ריק."},
        )

    if len(content_bytes) > MAX_BYTES:
        await _audit_failure(db, actor, safe_filename, document_type, authority_level, "file_too_large")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "file_too_large",
                "message": f"הקובץ גדול מדי. הגודל המרבי המותר הוא {MAX_BYTES // (1024 * 1024)} MB.",
            },
        )

    content_hash = sha256_hex(content_bytes)
    effective_url = source_url.strip() if source_url and source_url.strip() else f"upload://{safe_filename}"

    # ── Store in MinIO (raw content never goes anywhere else) ──────────────────
    bucket = settings.minio_bucket_documents
    object_key = _storage_key(content_hash, file_format)
    try:
        put_bytes(bucket, object_key, content_bytes, f"application/{file_format}")
    except Exception:
        await _audit_failure(db, actor, safe_filename, document_type, authority_level, "storage_error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "storage_error", "message": "שגיאה בשמירת הקובץ. אנא נסה שנית."},
        )

    # ── KnowledgeSource ────────────────────────────────────────────────────────
    ks = (
        await db.execute(select(KnowledgeSource).where(KnowledgeSource.name == title.strip()))
    ).scalar_one_or_none()

    if not ks:
        ks = KnowledgeSource(
            name=title.strip(),
            source_type="manual_upload",
            url=effective_url if source_url and source_url.strip() else None,
            authority_level=authority_level,
            is_active=True,
            context_type="government_ministries",
        )
        db.add(ks)
        await db.flush()

    # ── SourceDocument ─────────────────────────────────────────────────────────
    sd = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.knowledge_source_id == ks.id,
                SourceDocument.content_hash == content_hash,
            )
        )
    ).scalar_one_or_none()

    safe_metadata: dict = {
        "semantic_type": document_type.strip(),
        "file_format": file_format,
        "original_filename": safe_filename,
        "uploaded_by": str(actor.id),
    }
    if system_context and system_context.strip():
        safe_metadata["system_context"] = system_context.strip()[:500]
    if notes and notes.strip():
        safe_metadata["notes"] = notes.strip()[:500]

    if sd:
        sd.status = "downloaded"
        sd.storage_bucket = bucket
        sd.storage_object_key = object_key
        sd.last_seen_at = now
        sd.downloaded_at = now
        sd.metadata_json = safe_metadata
        await db.flush()
    else:
        sd = SourceDocument(
            knowledge_source_id=ks.id,
            url=effective_url,
            title=title.strip(),
            document_type=file_format,
            content_hash=content_hash,
            storage_bucket=bucket,
            storage_object_key=object_key,
            status="downloaded",
            first_seen_at=now,
            last_seen_at=now,
            downloaded_at=now,
            metadata_json=safe_metadata,
        )
        db.add(sd)
        await db.flush()

    # ── Audit success ──────────────────────────────────────────────────────────
    await record_audit_event(
        db,
        action="knowledge_document_uploaded",
        actor_user_id=actor.id,
        target_type="source_document",
        target_id=str(sd.id),
        metadata_json={
            "filename": safe_filename,
            "document_type": document_type.strip(),
            "authority_level": authority_level,
            "status": "downloaded",
            "file_format": file_format,
        },
    )

    await db.commit()

    return UploadResponse(
        document_id=str(sd.id),
        knowledge_source_id=str(ks.id),
        status="pending_processing",
        message="המסמך הועלה בהצלחה ועומד לעיבוד. הפעל את צינור האינדוקס להשלמת תהליך האינדוקס.",
    )


async def _audit_failure(
    db: AsyncSession,
    actor: User,
    filename: str,
    document_type: str,
    authority_level: int,
    error_category: str,
) -> None:
    try:
        await record_audit_event(
            db,
            action="knowledge_document_upload_failed",
            actor_user_id=actor.id,
            target_type="upload",
            target_id=None,
            metadata_json={
                "filename": filename,
                "document_type": document_type,
                "authority_level": authority_level,
                "error_category": error_category,
            },
        )
        await db.flush()
    except Exception:
        pass
