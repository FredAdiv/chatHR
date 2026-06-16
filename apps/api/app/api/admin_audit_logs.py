"""Admin: audit log viewer — list audit events for system_admin.

Privacy: no raw prompts, no document content, no PII exposed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.db.models.audit_log import AuditLog
from app.db.session import get_db

router = APIRouter(prefix="/admin/audit-logs", tags=["admin-audit"])

_AUDIT_ROLES = [RoleName.SYSTEM_ADMIN]


class AuditLogItem(BaseModel):
    id: str
    actor_user_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    metadata_json: dict | None
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total: int


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    action: str | None = Query(None, max_length=200),
    actor_user_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_any_role(_AUDIT_ROLES)),
) -> AuditLogListResponse:
    q = select(AuditLog).order_by(AuditLog.created_at.desc())

    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if actor_user_id:
        try:
            import uuid
            uid = uuid.UUID(actor_user_id)
            q = q.where(AuditLog.actor_user_id == uid)
        except ValueError:
            pass

    count_result = await db.execute(q)
    total = len(count_result.scalars().all())

    result = await db.execute(q.offset(offset).limit(limit))
    items = result.scalars().all()

    return AuditLogListResponse(
        total=total,
        items=[
            AuditLogItem(
                id=str(log.id),
                actor_user_id=str(log.actor_user_id) if log.actor_user_id else None,
                action=log.action,
                target_type=log.target_type,
                target_id=log.target_id,
                metadata_json=log.metadata_json,
                created_at=log.created_at.isoformat(),
            )
            for log in items
        ],
    )
