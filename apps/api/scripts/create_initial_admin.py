"""Bootstrap the initial system_admin user idempotently.

Run once after first migration:
    python -m scripts.create_initial_admin

Reads INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD from .env (or environment).
Does nothing if a user with that email already exists.
"""
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Allow running from repo root: python -m scripts.create_initial_admin
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.security import hash_password
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole


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

    async with Session() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            print(f"User '{email}' already exists — skipping.")
            await engine.dispose()
            return

        role = (await db.execute(select(Role).where(Role.name == "system_admin"))).scalar_one_or_none()
        if not role:
            print("ERROR: 'system_admin' role not found. Run seed_roles.py first.")
            sys.exit(1)

        user = User(email=email, display_name="Initial Admin", password_hash=hash_password(password))
        db.add(user)
        await db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        await db.commit()
        print(f"Created system_admin user: {email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
