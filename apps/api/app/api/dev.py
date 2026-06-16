"""
DEV-ONLY endpoints for local development smoke-checks.
These must NOT be exposed in production as-is.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.core.roles import RoleName
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/db-info")
async def dev_db_info(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role(RoleName.SYSTEM_ADMIN)),
):
    """Return non-sensitive DB readiness info and role count. DEV ONLY."""
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM roles"))
        role_count = result.scalar()
        return {
            "status": "connected",
            "role_count": role_count,
            "warning": "DEV ONLY — do not expose in production",
        }
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}
