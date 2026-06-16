import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api"))

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.roles import (
    REQUIRED_ROLES,
    RoleName,
    require_any_role,
    require_role,
    user_has_any_role,
    user_has_role,
)


def _make_user(*role_names: str):
    """Build a lightweight mock User with the given roles attached.

    Note: MagicMock(name=...) sets the mock's internal repr name, not an
    attribute. Use SimpleNamespace for plain attribute access instead.
    """
    user = MagicMock()
    user.user_roles = [
        SimpleNamespace(role=SimpleNamespace(name=name)) for name in role_names
    ]
    return user


def test_required_roles_all_present():
    expected = {"chat_user", "faq_manager", "user_admin", "feedback_reviewer", "knowledge_admin", "system_admin"}
    assert set(REQUIRED_ROLES) == expected


def test_role_name_enum_values():
    assert RoleName.CHAT_USER == "chat_user"
    assert RoleName.SYSTEM_ADMIN == "system_admin"


def test_user_has_role_true():
    user = _make_user("chat_user", "faq_manager")
    assert user_has_role(user, "chat_user")
    assert user_has_role(user, "faq_manager")


def test_user_has_role_false():
    user = _make_user("chat_user")
    assert not user_has_role(user, "system_admin")


def test_user_has_any_role():
    user = _make_user("faq_manager")
    assert user_has_any_role(user, ["faq_manager", "system_admin"])
    assert not user_has_any_role(user, ["user_admin", "system_admin"])


def test_require_role_passes():
    user = _make_user("knowledge_admin")
    require_role(user, "knowledge_admin")  # should not raise


def test_require_role_raises():
    user = _make_user("chat_user")
    with pytest.raises(PermissionError):
        require_role(user, "system_admin")


def test_require_any_role_passes():
    user = _make_user("feedback_reviewer")
    require_any_role(user, ["feedback_reviewer", "system_admin"])


def test_require_any_role_raises():
    user = _make_user("chat_user")
    with pytest.raises(PermissionError):
        require_any_role(user, ["system_admin", "knowledge_admin"])
