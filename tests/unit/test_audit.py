import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit import record_audit_event


@pytest.mark.asyncio
async def test_record_audit_event_basic():
    """record_audit_event should add an AuditLog entry to the session."""
    session = AsyncMock()
    session.flush = AsyncMock()

    entry = await record_audit_event(
        session,
        action="user.created",
        actor_user_id=uuid.uuid4(),
        target_type="user",
        target_id=str(uuid.uuid4()),
    )

    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    assert entry.action == "user.created"


@pytest.mark.asyncio
async def test_record_audit_event_no_prompt_content():
    """Audit entries should not require or store prompt content."""
    session = AsyncMock()
    session.flush = AsyncMock()

    entry = await record_audit_event(session, action="index.activated")
    assert entry.metadata_json is None  # no prompt data stored


@pytest.mark.asyncio
async def test_record_audit_event_system_actor():
    """actor_user_id may be None for system-initiated events."""
    session = AsyncMock()
    session.flush = AsyncMock()

    entry = await record_audit_event(session, action="index.quality_check_failed")
    assert entry.actor_user_id is None
