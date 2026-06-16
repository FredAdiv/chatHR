import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog


async def record_audit_event(
    session: AsyncSession,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata_json: dict | None = None,
) -> AuditLog:
    """
    Write one audit-log entry.
    - Never include secrets or full prompt content in metadata_json.
    - actor_user_id may be None for system-initiated events.
    """
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        target_type=target_type,
        target_id=target_id,
        metadata_json=metadata_json,
    )
    session.add(entry)
    await session.flush()
    return entry
