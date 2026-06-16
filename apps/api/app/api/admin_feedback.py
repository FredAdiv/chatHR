"""Admin: feedback dashboard — list answer feedback for feedback_reviewer / system_admin.

Privacy: only rating + anonymized comment shown; no user PII, no raw prompt content.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.feedback import AnswerFeedback
from app.db.models.message import Message
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/feedback", tags=["admin-feedback"])

_FEEDBACK_ROLES = [RoleName.FEEDBACK_REVIEWER, RoleName.SYSTEM_ADMIN]


class FeedbackItem(BaseModel):
    id: str
    message_id: str
    conversation_id: str | None
    rating: str
    comment: str | None
    created_at: str


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItem]
    total: int


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    rating: str | None = Query(None, pattern="^(positive|negative)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_any_role(_FEEDBACK_ROLES)),
) -> FeedbackListResponse:
    await record_audit_event(
        db,
        action="view_feedback_dashboard",
        actor_user_id=actor.id,
        target_type="feedback",
        target_id=None,
        metadata_json={"rating_filter": rating},
    )

    q = select(AnswerFeedback).order_by(AnswerFeedback.created_at.desc())
    if rating:
        q = q.where(AnswerFeedback.rating == rating)

    count_result = await db.execute(q)
    total = len(count_result.scalars().all())

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    items = result.scalars().all()

    msg_ids = list({fb.message_id for fb in items})
    conv_map: dict[uuid.UUID, uuid.UUID | None] = {}
    if msg_ids:
        msgs_result = await db.execute(
            select(Message.id, Message.conversation_id).where(Message.id.in_(msg_ids))
        )
        for mid, cid in msgs_result.all():
            conv_map[mid] = cid

    await db.commit()

    return FeedbackListResponse(
        total=total,
        items=[
            FeedbackItem(
                id=str(fb.id),
                message_id=str(fb.message_id),
                conversation_id=str(conv_map.get(fb.message_id)) if conv_map.get(fb.message_id) else None,
                rating=fb.rating,
                comment=fb.comment,
                created_at=fb.created_at.isoformat(),
            )
            for fb in items
        ],
    )
