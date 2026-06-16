import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.core.roles import user_has_any_role, user_has_role
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    try:
        user_id = decode_token(token)
    except jwt.PyJWTError:
        raise credentials_exc
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise credentials_exc

    result = await db.execute(
        select(User)
        .where(User.id == user_uuid)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


def require_role(role_name: str) -> Callable:
    async def _dep(current_user: User = Depends(get_current_active_user)) -> User:
        if not user_has_role(current_user, role_name):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{role_name}' required")
        return current_user

    return _dep


def require_any_role(role_names: list[str]) -> Callable:
    async def _dep(current_user: User = Depends(get_current_active_user)) -> User:
        if not user_has_any_role(current_user, role_names):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"One of roles {role_names} required")
        return current_user

    return _dep
