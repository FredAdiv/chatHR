import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.config import settings
from app.core.roles import RoleName
from app.db.models.index_version import IndexVersion
from app.services.embeddings.gateway import get_embedding_dimension
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/index-versions", tags=["index-versions"])

_IV_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

IndexVersionStatus = Literal["building", "draft", "quality_check_failed", "ready", "active", "archived"]

# Allowed statuses for manual archive (active version is replaced via activate, not archived directly)
_ARCHIVABLE_STATUSES = {"draft", "ready", "quality_check_failed"}


class IndexVersionCreate(BaseModel):
    version_label: str
    # embedding_model is optional — defaults to current provider's configured model
    embedding_model: str | None = None
    # Must not contain prompts, secrets, tokens, PII, or raw source content
    metadata_json: dict | None = None

    @field_validator("version_label")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class IndexVersionResponse(BaseModel):
    id: str
    version_label: str
    status: str
    embedding_model: str
    embedding_provider: str | None
    embedding_dimensions: int | None
    created_by_user_id: str | None
    activated_by_user_id: str | None
    created_at: str | None
    activated_at: str | None
    metadata_json: dict | None
    embedding_warning: str | None = None


def _iv_dict(iv: IndexVersion) -> dict:
    provider = iv.embedding_provider or "fake-local"
    warning = None
    if provider == "fake-local":
        warning = "fake-local embeddings — retrieval is not semantically meaningful"
    return {
        "id": str(iv.id),
        "version_label": iv.version_label,
        "status": iv.status,
        "embedding_model": iv.embedding_model,
        "embedding_provider": iv.embedding_provider,
        "embedding_dimensions": iv.embedding_dimensions,
        "created_by_user_id": str(iv.created_by_user_id) if iv.created_by_user_id else None,
        "activated_by_user_id": str(iv.activated_by_user_id) if iv.activated_by_user_id else None,
        "created_at": iv.created_at.isoformat() if iv.created_at else None,
        "activated_at": iv.activated_at.isoformat() if iv.activated_at else None,
        "metadata_json": iv.metadata_json,
        "embedding_warning": warning,
    }


@router.get("", response_model=list[IndexVersionResponse])
async def list_index_versions(
    index_status: IndexVersionStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_IV_ROLES)),
):
    q = select(IndexVersion)
    if index_status:
        q = q.where(IndexVersion.status == index_status)
    result = await db.execute(q)
    return [_iv_dict(iv) for iv in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=IndexVersionResponse)
async def create_index_version(
    req: IndexVersionCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_IV_ROLES)),
):
    now = datetime.now(timezone.utc)
    # Resolve embedding metadata from current settings/provider
    emb_provider = settings.embedding_provider
    emb_dimensions = get_embedding_dimension(emb_provider)
    if req.embedding_model:
        emb_model = req.embedding_model
    elif emb_provider == "fake-local":
        emb_model = settings.embedding_model
    else:
        emb_model = settings.openrouter_embedding_model

    # Status is always "building" on create — clients cannot set it directly
    iv = IndexVersion(
        id=uuid.uuid4(),
        version_label=req.version_label,
        status="building",
        embedding_model=emb_model,
        embedding_provider=emb_provider,
        embedding_dimensions=emb_dimensions,
        created_by_user_id=actor.id,
        metadata_json=req.metadata_json,
        created_at=now,
    )
    db.add(iv)
    await db.flush()
    await record_audit_event(
        db,
        action="index_version_created",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(iv.id),
        metadata_json={"version_label": iv.version_label, "embedding_model": iv.embedding_model},
    )
    await db.commit()
    return _iv_dict(iv)


@router.patch("/{version_id}/mark-ready", response_model=IndexVersionResponse)
async def mark_index_version_ready(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_IV_ROLES)),
):
    iv = await db.get(IndexVersion, version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found")
    if iv.status not in {"building", "draft"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only building or draft index versions can be marked ready (current status: {iv.status})",
        )
    iv.status = "ready"
    await record_audit_event(
        db,
        action="index_version_marked_ready",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(version_id),
    )
    await db.commit()
    return _iv_dict(iv)


@router.patch("/{version_id}/mark-quality-failed", response_model=IndexVersionResponse)
async def mark_index_version_quality_failed(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_IV_ROLES)),
):
    iv = await db.get(IndexVersion, version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found")
    _QUALITY_FAIL_ALLOWED = {"building", "draft", "ready"}
    if iv.status not in _QUALITY_FAIL_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot mark index version with status '{iv.status}' as quality failed (allowed: building, ready)",
        )
    iv.status = "quality_check_failed"
    await record_audit_event(
        db,
        action="index_version_quality_failed",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(version_id),
    )
    await db.commit()
    return _iv_dict(iv)


@router.patch("/{version_id}/activate", response_model=IndexVersionResponse)
async def activate_index_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_IV_ROLES)),
):
    iv = await db.get(IndexVersion, version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found")
    if iv.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only ready index versions can be activated (current status: {iv.status})",
        )

    # Archive any currently active version — never update the active index directly
    active_result = await db.execute(select(IndexVersion).where(IndexVersion.status == "active"))
    for active_iv in active_result.scalars().all():
        active_iv.status = "archived"
        await record_audit_event(
            db,
            action="index_version_archived",
            actor_user_id=actor.id,
            target_type="index_version",
            target_id=str(active_iv.id),
            metadata_json={"reason": "replaced_by_activation", "new_version_id": str(version_id)},
        )

    now = datetime.now(timezone.utc)
    iv.status = "active"
    iv.activated_by_user_id = actor.id
    iv.activated_at = now
    await record_audit_event(
        db,
        action="index_version_activated",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(version_id),
    )
    await db.commit()
    return _iv_dict(iv)


@router.patch("/{version_id}/archive", response_model=IndexVersionResponse)
async def archive_index_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_IV_ROLES)),
):
    iv = await db.get(IndexVersion, version_id)
    if not iv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Index version not found")
    if iv.status == "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot archive the active index version directly. Activate a newer ready version to replace it.",
        )
    if iv.status not in _ARCHIVABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot archive index version with status '{iv.status}'",
        )
    iv.status = "archived"
    await record_audit_event(
        db,
        action="index_version_archived",
        actor_user_id=actor.id,
        target_type="index_version",
        target_id=str(version_id),
    )
    await db.commit()
    return _iv_dict(iv)
