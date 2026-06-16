#!/usr/bin/env python
"""Seed required roles. Idempotent — safe to run multiple times."""
import os
import uuid

import psycopg2

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://chathr_user:CHANGE_ME@postgres:5432/chathr",
)

REQUIRED_ROLES = (
    "chat_user",
    "faq_manager",
    "user_admin",
    "feedback_reviewer",
    "knowledge_admin",
    "system_admin",
)


def seed_roles() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for role_name in REQUIRED_ROLES:
                cur.execute(
                    "INSERT INTO roles (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (str(uuid.uuid4()), role_name),
                )
        conn.commit()
        print(f"Seeded {len(REQUIRED_ROLES)} roles (idempotent).")
    finally:
        conn.close()


if __name__ == "__main__":
    seed_roles()
