import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.faq_item import FaqItem
from app.db.models.user import User
from app.db.session import get_db
from app.services.audit import record_audit_event
from app.services.faq.retrieval_sync import remove_faq_from_retrieval, sync_faq_to_retrieval

router = APIRouter(prefix="/admin/faq", tags=["faq"])

_FAQ_ROLES = [RoleName.FAQ_MANAGER, RoleName.SYSTEM_ADMIN]

ContextType = Literal["government_ministries", "defense_system", "health_system"]
FaqStatus = Literal["draft", "approved", "archived"]


class FaqCreate(BaseModel):
    question: str
    answer: str
    topic: str | None = None
    context_type: ContextType | None = None
    applicable_population: str | None = None
    official_source_links: list[str] = []

    @field_validator("question", "answer")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class FaqUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    topic: str | None = None
    context_type: ContextType | None = None
    applicable_population: str | None = None
    official_source_links: list[str] | None = None

    @field_validator("question", "answer")
    @classmethod
    def not_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be empty")
        return v


class FaqResponse(BaseModel):
    id: str
    question: str
    answer: str
    topic: str | None
    context_type: str | None
    applicable_population: str | None
    official_source_links: list
    status: str
    approved_by_user_id: str | None
    approved_at: str | None
    content_version: int
    created_at: str | None
    updated_at: str | None


_CONTENT_FIELDS = {"question", "answer", "topic", "context_type", "applicable_population", "official_source_links"}


def _faq_dict(item: FaqItem) -> dict:
    return {
        "id": str(item.id),
        "question": item.question,
        "answer": item.answer,
        "topic": item.topic,
        "context_type": item.context_type,
        "applicable_population": item.applicable_population,
        "official_source_links": item.official_source_links,
        "status": item.status,
        "approved_by_user_id": str(item.approved_by_user_id) if item.approved_by_user_id else None,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "content_version": item.content_version,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("", response_model=list[FaqResponse])
async def list_faq(
    status: FaqStatus | None = Query(default=None),
    context_type: ContextType | None = Query(default=None),
    topic: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_FAQ_ROLES)),
):
    q = select(FaqItem)
    if status:
        q = q.where(FaqItem.status == status)
    if context_type:
        q = q.where(FaqItem.context_type == context_type)
    if topic:
        q = q.where(FaqItem.topic == topic)
    result = await db.execute(q)
    return [_faq_dict(item) for item in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=FaqResponse)
async def create_faq(
    req: FaqCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_FAQ_ROLES)),
):
    now = datetime.now(timezone.utc)
    item = FaqItem(
        id=uuid.uuid4(),
        question=req.question,
        answer=req.answer,
        topic=req.topic,
        context_type=req.context_type,
        applicable_population=req.applicable_population,
        official_source_links=req.official_source_links,
        status="draft",
        content_version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.flush()
    await record_audit_event(
        db,
        action="faq_created",
        actor_user_id=actor.id,
        target_type="faq_item",
        target_id=str(item.id),
        metadata_json={"status": "draft", "context_type": item.context_type, "topic": item.topic},
    )
    await db.commit()
    return _faq_dict(item)


@router.patch("/{faq_id}", response_model=FaqResponse)
async def update_faq(
    faq_id: uuid.UUID,
    req: FaqUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_FAQ_ROLES)),
):
    item = await db.get(FaqItem, faq_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ item not found")
    if item.status == "archived":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Archived FAQ items cannot be edited")

    update_data = req.model_dump(exclude_unset=True)
    content_changed = any(
        field in _CONTENT_FIELDS and getattr(item, field) != value
        for field, value in update_data.items()
    )
    will_revert_to_draft = content_changed and item.status == "approved"

    for field, value in update_data.items():
        setattr(item, field, value)

    if content_changed:
        item.content_version += 1
        if will_revert_to_draft:
            item.status = "draft"
            item.approved_by_user_id = None
            item.approved_at = None

    item.updated_at = datetime.now(timezone.utc)

    if will_revert_to_draft:
        await remove_faq_from_retrieval(db, faq_id, actor_user_id=actor.id)

    await record_audit_event(
        db, action="faq_updated", actor_user_id=actor.id,
        target_type="faq_item", target_id=str(faq_id),
    )
    await db.commit()
    return _faq_dict(item)


@router.patch("/{faq_id}/approve", response_model=FaqResponse)
async def approve_faq(
    faq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_FAQ_ROLES)),
):
    item = await db.get(FaqItem, faq_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ item not found")
    if item.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archived FAQ items cannot be approved")

    now = datetime.now(timezone.utc)
    item.status = "approved"
    item.approved_by_user_id = actor.id
    item.approved_at = now
    item.updated_at = now
    await db.flush()
    await sync_faq_to_retrieval(db, item, actor_user_id=actor.id)
    await record_audit_event(
        db, action="faq_approved", actor_user_id=actor.id,
        target_type="faq_item", target_id=str(faq_id),
    )
    await db.commit()
    return _faq_dict(item)


@router.patch("/{faq_id}/archive", response_model=FaqResponse)
async def archive_faq(
    faq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_FAQ_ROLES)),
):
    item = await db.get(FaqItem, faq_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="FAQ item not found")

    item.status = "archived"
    item.updated_at = datetime.now(timezone.utc)
    await remove_faq_from_retrieval(db, faq_id, actor_user_id=actor.id)
    await record_audit_event(
        db, action="faq_archived", actor_user_id=actor.id,
        target_type="faq_item", target_id=str(faq_id),
    )
    await db.commit()
    return _faq_dict(item)
