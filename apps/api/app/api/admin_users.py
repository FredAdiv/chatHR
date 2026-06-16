import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_any_role
from app.core.roles import RoleName
from app.core.security import hash_password
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/admin/users", tags=["admin"])

_ADMIN_ROLES = [RoleName.USER_ADMIN, RoleName.SYSTEM_ADMIN]


class CreateUserRequest(BaseModel):
    email: str
    display_name: str | None = None
    password: str
    roles: list[str] = []


class UpdateRolesRequest(BaseModel):
    roles: list[str]


async def _resolve_roles(db: AsyncSession, role_names: list[str]) -> dict[str, Role]:
    if not role_names:
        return {}
    result = await db.execute(select(Role).where(Role.name.in_(role_names)))
    found = {r.name: r for r in result.scalars().all()}
    invalid = set(role_names) - set(found)
    if invalid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown roles: {sorted(invalid)}")
    return found


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_any_role(_ADMIN_ROLES)),
):
    result = await db.execute(
        select(User).options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "is_active": u.is_active,
            "roles": [ur.role.name for ur in u.user_roles],
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    req: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_ADMIN_ROLES)),
):
    role_map = await _resolve_roles(db, req.roles)

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=req.email, display_name=req.display_name, password_hash=hash_password(req.password))
    db.add(user)
    await db.flush()

    for role in role_map.values():
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await record_audit_event(db, action="user_created", actor_user_id=actor.id, target_type="user", target_id=str(user.id))
    await db.commit()

    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "roles": list(role_map)}


@router.patch("/{user_id}/roles")
async def update_roles(
    user_id: uuid.UUID,
    req: UpdateRolesRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_ADMIN_ROLES)),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role_map = await _resolve_roles(db, req.roles)

    existing_urs = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    for ur in existing_urs.scalars().all():
        await db.delete(ur)

    for role in role_map.values():
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await record_audit_event(
        db, action="user_roles_updated", actor_user_id=actor.id,
        target_type="user", target_id=str(user_id),
        metadata_json={"new_roles": req.roles},
    )
    await db.commit()
    return {"id": str(user_id), "roles": list(role_map)}


@router.patch("/{user_id}/deactivate")
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_any_role(_ADMIN_ROLES)),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    await record_audit_event(db, action="user_deactivated", actor_user_id=actor.id, target_type="user", target_id=str(user_id))
    await db.commit()
    return {"id": str(user_id), "is_active": False}
