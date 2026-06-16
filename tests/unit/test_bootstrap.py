"""Tests for the bootstrap_admin function in create_initial_admin.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api", "scripts"))

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from create_initial_admin import bootstrap_admin
from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.db.models.user_role import UserRole


def _roles_db_side_effects(user_exists=False):
    """Build the two DB execute results needed by bootstrap_admin."""
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = (
        SimpleNamespace(id=uuid.uuid4()) if user_exists else None
    )
    role_scalars = MagicMock()
    role_scalars.all.return_value = [
        SimpleNamespace(id=uuid.uuid4(), name="system_admin"),
        SimpleNamespace(id=uuid.uuid4(), name="user_admin"),
    ]
    roles_result = MagicMock()
    roles_result.scalars.return_value = role_scalars
    return [user_result, roles_result]


def _make_db(side_effects):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effects)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_bootstrap_idempotent_if_user_exists():
    """When user already exists, bootstrap_admin must return created=False and add nothing."""
    user_result = MagicMock()
    existing = SimpleNamespace(id=uuid.uuid4())
    user_result.scalar_one_or_none.return_value = existing
    db = _make_db([user_result])

    result = await bootstrap_admin(db, "admin@test.com", "irrelevant")

    assert result["created"] is False
    assert result["user_id"] == str(existing.id)
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_bootstrap_assigns_system_admin_and_user_admin():
    """bootstrap_admin must create UserRole entries for both system_admin and user_admin."""
    db = _make_db(_roles_db_side_effects(user_exists=False))

    result = await bootstrap_admin(db, "admin@test.com", "StrongPass1!")

    assert result["created"] is True
    added = [c.args[0] for c in db.add.call_args_list]
    user_roles = [a for a in added if isinstance(a, UserRole)]
    assert len(user_roles) == 2


@pytest.mark.asyncio
async def test_bootstrap_records_bootstrap_initial_admin_audit():
    """bootstrap_admin must record an audit event with action='bootstrap_initial_admin'."""
    db = _make_db(_roles_db_side_effects(user_exists=False))

    await bootstrap_admin(db, "admin@test.com", "StrongPass1!")

    added = [c.args[0] for c in db.add.call_args_list]
    audit_entries = [a for a in added if isinstance(a, AuditLog)]
    assert len(audit_entries) == 1
    assert audit_entries[0].action == "bootstrap_initial_admin"
    assert audit_entries[0].actor_user_id is None


@pytest.mark.asyncio
async def test_bootstrap_missing_roles_raises_helpful_error():
    """When seed_roles has not been run, bootstrap_admin must raise RuntimeError with guidance."""
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None
    empty_scalars = MagicMock()
    empty_scalars.all.return_value = []
    empty_roles_result = MagicMock()
    empty_roles_result.scalars.return_value = empty_scalars
    db = _make_db([user_result, empty_roles_result])

    with pytest.raises(RuntimeError, match="seed_roles"):
        await bootstrap_admin(db, "admin@test.com", "StrongPass1!")
