from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.models.user import User


class RoleName(StrEnum):
    CHAT_USER = "chat_user"
    FAQ_MANAGER = "faq_manager"
    USER_ADMIN = "user_admin"
    FEEDBACK_REVIEWER = "feedback_reviewer"
    KNOWLEDGE_ADMIN = "knowledge_admin"
    SYSTEM_ADMIN = "system_admin"


REQUIRED_ROLES: tuple[str, ...] = tuple(r.value for r in RoleName)


def user_has_role(user: "User", role_name: str) -> bool:
    return any(ur.role.name == role_name for ur in user.user_roles)


def user_has_any_role(user: "User", role_names: list[str]) -> bool:
    user_role_names = {ur.role.name for ur in user.user_roles}
    return bool(user_role_names & set(role_names))


def require_role(user: "User", role_name: str) -> None:
    if not user_has_role(user, role_name):
        raise PermissionError(f"Role '{role_name}' required.")


def require_any_role(user: "User", role_names: list[str]) -> None:
    if not user_has_any_role(user, role_names):
        raise PermissionError(f"One of roles {role_names} required.")
