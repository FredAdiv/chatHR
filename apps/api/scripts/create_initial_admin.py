"""Bootstrap the initial system_admin + user_admin user idempotently.

Run once after first migration and seed_roles:
    python -m scripts.create_initial_admin

Reads INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD from .env (or environment).
Does nothing if a user with that email already exists.
"""
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.services.audit import record_audit_event

_REQUIRED_ROLES = ["system_admin", "user_admin"]


async def bootstrap_admin(db: AsyncSession, email: str, password: str) -> dict:
    """Idempotently create the initial admin user with system_admin + user_admin roles.

    Returns {"created": True, "user_id": str} or {"created": False, "user_id": str}.
    Raises RuntimeError if required roles are missing (run seed_roles.py first).
    Never stores or prints plain password.
    """
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return {"created": False, "user_id": str(existing.id)}

    roles_result = await db.execute(select(Role).where(Role.name.in_(_REQUIRED_ROLES)))
    roles = {r.name: r for r in roles_result.scalars().all()}

    missing = set(_REQUIRED_ROLES) - set(roles)
    if missing:
        raise RuntimeError(
            f"Required roles not found: {sorted(missing)}. Run seed_roles.py first."
        )

    user = User(email=email, display_name="Initial Admin", password_hash=hash_password(password))
    db.add(user)
    await db.flush()

    for role in roles.values():
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await record_audit_event(
        db,
        action="bootstrap_initial_admin",
        actor_user_id=None,
        target_type="user",
        target_id=str(user.id),
        metadata_json={"email": email},
    )

    await db.commit()
    return {"created": True, "user_id": str(user.id)}


async def main() -> None:
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "")
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")

    if not email or not password:
        print("ERROR: INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD must be set in environment.")
        sys.exit(1)
    if password == "CHANGE_ME":
        print("ERROR: Do not use the placeholder password from .env.example.")
        sys.exit(1)

    engine = create_async_engine(settings.async_database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            result = await bootstrap_admin(db, email, password)
            if result["created"]:
                print(f"Created initial admin user: {email} (id={result['user_id']})")
            else:
                print(f"User '{email}' already exists — skipping.")
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
