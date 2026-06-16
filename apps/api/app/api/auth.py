from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_active_user
from app.core.security import create_access_token, verify_password
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.db.session import get_db
from app.services.audit import record_audit_event

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.email == form.username)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active or not user.password_hash or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    user.last_login_at = datetime.now(timezone.utc)
    await record_audit_event(db, action="user.login", actor_user_id=user.id, target_type="user", target_id=str(user.id))
    await db.commit()

    return {"access_token": create_access_token(str(user.id)), "token_type": "bearer"}


@router.get("/me")
async def me(current_user: User = Depends(get_current_active_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "is_active": current_user.is_active,
        "roles": [ur.role.name for ur in current_user.user_roles],
    }
