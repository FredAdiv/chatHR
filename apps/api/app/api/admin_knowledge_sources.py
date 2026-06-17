import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.knowledge_source import KnowledgeSource
from app.db.models.knowledge_source_context import (
    ALLOWED_CONTEXT_VALUES,
    KnowledgeSourceContext,
)
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/knowledge-sources", tags=["knowledge-sources"])

_KS_ROLES = [RoleName.KNOWLEDGE_ADMIN, RoleName.SYSTEM_ADMIN]

_AUTHORITY_MIN = 1
_AUTHORITY_MAX = 5

ContextType = Literal["government_ministries", "defense_system", "health_system"]
ContextTypeWithGeneral = Literal[
    "government_ministries", "defense_system", "health_system", "general"
]


def _validate_contexts(contexts: list[str]) -> list[str]:
    invalid = [c for c in contexts if c not in ALLOWED_CONTEXT_VALUES]
    if invalid:
        raise ValueError(f"Invalid context values: {invalid}. Allowed: {sorted(ALLOWED_CONTEXT_VALUES)}")
    return list(dict.fromkeys(contexts))  # deduplicate preserving order


class KnowledgeSourceCreate(BaseModel):
    name: str
    source_type: str
    url: str | None = None
    authority_level: int
    is_active: bool = True
    contexts: list[ContextTypeWithGeneral] = []

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

    @field_validator("contexts")
    @classmethod
    def valid_contexts(cls, v: list[str]) -> list[str]:
        return _validate_contexts(v)


class KnowledgeSourceUpdate(BaseModel):
    name: str | None = None
    source_type: str | None = None
    url: str | None = None
    authority_level: int | None = None
    is_active: bool | None = None
    contexts: list[ContextTypeWithGeneral] | None = None

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

    @field_validator("contexts")
    @classmethod
    def valid_contexts(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            return _validate_contexts(v)
        return v


class KnowledgeSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    url: str | None
    authority_level: int
    is_active: bool
    contexts: list[str]
    created_at: str | None
    updated_at: str | None


async def _load_contexts(db: AsyncSession, source_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(KnowledgeSourceContext.context_type)
        .where(KnowledgeSourceContext.knowledge_source_id == source_id)
        .order_by(KnowledgeSourceContext.context_type)
    )
    return list(result.scalars().all())


async def _set_contexts(
    db: AsyncSession, source_id: uuid.UUID, contexts: list[str]
) -> None:
    await db.execute(
        delete(KnowledgeSourceContext).where(
            KnowledgeSourceContext.knowledge_source_id == source_id
        )
    )
    for ctx in contexts:
        db.add(KnowledgeSourceContext(
            id=uuid.uuid4(),
            knowledge_source_id=source_id,
            context_type=ctx,
        ))
    await db.flush()


async def _ks_response(db: AsyncSession, source: KnowledgeSource) -> dict:
    contexts = await _load_contexts(db, source.id)
    return {
        "id": str(source.id),
        "name": source.name,
        "source_type": source.source_type,
        "url": source.url,
        "authority_level": source.authority_level,
        "is_active": source.is_active,
        "contexts": contexts,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


@router.get("", response_model=list[KnowledgeSourceResponse])
async def list_knowledge_sources(
    is_active: bool | None = Query(default=None),
    authority_level: int | None = Query(default=None, ge=_AUTHORITY_MIN, le=_AUTHORITY_MAX),
    source_type: str | None = Query(default=None),
    context_type: ContextTypeWithGeneral | None = Query(default=None),
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
    if context_type is not None:
        from sqlalchemy import exists as _exists
        q = q.where(
            _exists().where(
                (KnowledgeSourceContext.knowledge_source_id == KnowledgeSource.id)
                & (KnowledgeSourceContext.context_type == context_type)
            )
        )
    sources = (await db.execute(q)).scalars().all()
    return [await _ks_response(db, s) for s in sources]


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

    if req.contexts:
        await _set_contexts(db, source.id, req.contexts)

    await record_audit_event(
        db,
        action="knowledge_source_created",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source.id),
        metadata_json={
            "name": source.name,
            "authority_level": source.authority_level,
            "contexts": req.contexts,
        },
    )
    await db.commit()
    return await _ks_response(db, source)


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

    data = req.model_dump(exclude_unset=True)
    contexts = data.pop("contexts", None)

    for field, value in data.items():
        setattr(source, field, value)
    source.updated_at = datetime.now(timezone.utc)

    if contexts is not None:
        await _set_contexts(db, source_id, contexts)

    await record_audit_event(
        db,
        action="knowledge_source_updated",
        actor_user_id=actor.id,
        target_type="knowledge_source",
        target_id=str(source_id),
        metadata_json={"contexts_updated": contexts is not None},
    )
    await db.commit()
    return await _ks_response(db, source)


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
    return await _ks_response(db, source)


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
    return await _ks_response(db, source)
