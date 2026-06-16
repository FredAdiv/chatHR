import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/knowledge-sources", tags=["knowledge-sources"])

_KS_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

# Authority hierarchy:
# 1 = salary agreements / תקשי"ר (highest authority)
# 2 = commissioner guidelines / official circulars / binding procedures
# 3 = policy documents / implementation guidelines / helper documents
# 4 = approved FAQ
# 5 = general explanatory documents (lowest authority)
_AUTHORITY_MIN = 1
_AUTHORITY_MAX = 5


class KnowledgeSourceCreate(BaseModel):
    name: str
    source_type: str
    url: str | None = None
    authority_level: int
    is_active: bool = True

    @field_validator("name", "source_type")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("authority_level")
    @classmethod
    def valid_authority(cls, v: int) -> int:
        if v < _AUTHORITY_MIN or v > _AUTHORITY_MAX:
            raise ValueError(f"authority_level must be between {_AUTHORITY_MIN} and {_AUTHORITY_MAX}")
        return v


class KnowledgeSourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    url: str | None = None
    authority_level: int | None = None
    is_active: bool | None = None

    @field_validator("name", "source_type")
    @classmethod
    def not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("authority_level")
    @classmethod
    def valid_authority(cls, v: int | None) -> int | None:
        if v is not None and (v < _AUTHORITY_MIN or v > _AUTHORITY_MAX):
            raise ValueError(f"authority_level must be between {_AUTHORITY_MIN} and {_AUTHORITY_MAX}")
        return v


class KnowledgeSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    url: str | None
    authority_level: int
    is_active: bool
    created_at: str | None
    updated_at: str | None


def _ks_dict(source: KnowledgeSource) -> dict:
    return {
        "id": str(source.id),
        "name": source.name,
        "source_type": source.source_type,
        "url": source.url,
        "authority_level": source.authority_level,
        "is_active": source.is_active,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


@router.get("", response_model=list[KnowledgeSourceResponse])
async def list_knowledge_sources(
    is_active: bool | None = Query(default=None),
    authority_level: int | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_KS_ROLES)),
):
    q = select(KnowledgeSource)
    if is_active is not None:
        q = q.where(KnowledgeSource.is_active == is_active)
    if authority_level is not None:
        q = q.where(KnowledgeSource.authority_level == authority_level)
    if source_type:
        q = q.where(KnowledgeSource.source_type == source_type)
    result = await db.execute(q)
    return [_ks_dict(s) for s in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=KnowledgeSourceResponse)
async def create_knowledge_source(
    req: KnowledgeSourceCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_KS_ROLES)),
):
    now = datetime.now(timezone.utc)
    source = KnowledgeSource(
        id=uuid.uuid4(),
        name=req.name,
        source_type=req.source_type,
        url=req.url,
        authority_level=req.authority_level,
        is_active=req.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(source)
    await db.flush()
    await record_audit_event(
        db,
        action="knowledge_source_created",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source.id),
        metadata_json={"name": source.name, "authority_level": source.authority_level},
    )
    await db.commit()
    return _ks_dict(source)


@router.patch("/{source_id}", response_model=KnowledgeSourceResponse)
async def update_knowledge_source(
    source_id: uuid.UUID,
    req: KnowledgeSourceUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_KS_ROLES)),
):
    source = await db.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    source.updated_at = datetime.now(timezone.utc)
    await record_audit_event(
        db,
        action="knowledge_source_updated",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source_id),
    )
    await db.commit()
    return _ks_dict(source)


@router.patch("/{source_id}/deactivate", response_model=KnowledgeSourceResponse)
async def deactivate_knowledge_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_KS_ROLES)),
):
    source = await db.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    source.is_active = False
    source.updated_at = datetime.now(timezone.utc)
    await record_audit_event(
        db,
        action="knowledge_source_deactivated",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source_id),
    )
    await db.commit()
    return _ks_dict(source)


@router.patch("/{source_id}/activate", response_model=KnowledgeSourceResponse)
async def activate_knowledge_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_KS_ROLES)),
):
    source = await db.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    source.is_active = True
    source.updated_at = datetime.now(timezone.utc)
    await record_audit_event(
        db,
        action="knowledge_source_activated",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source_id),
    )
    await db.commit()
    return _ks_dict(source)
