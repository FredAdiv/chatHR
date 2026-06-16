# ChatHR – Database

## Stack

- PostgreSQL 16 with `pgvector` extension (via `pgvector/pgvector:pg16` Docker image)
- SQLAlchemy 2.0 (async, `asyncpg` driver at runtime)
- Alembic for schema migrations (sync, `psycopg2` driver)

## Schema Overview

| Table | Description |
|---|---|
| `users` | System users (HR employees with access) |
| `roles` | Named permission roles |
| `user_roles` | Many-to-many: user ↔ role |
| `conversations` | Chat sessions, scoped to a civil service context |
| `messages` | Chat messages (user / assistant / system) |
| `answer_feedback` | Thumbs up/down + comment per message |
| `audit_log` | Immutable record of all administrative actions |
| `faq_items` | Approved HR FAQ entries indexed in RAG |
| `knowledge_sources` | Registered official document sources |
| `index_versions` | RAG index build lifecycle |

### Civil Service Contexts

All context-scoped tables accept one of:
- `government_ministries`
- `defense_system`
- `health_system`

### Required Role Names

| Role | Purpose |
|---|---|
| `chat_user` | Ask HR questions |
| `faq_manager` | Manage FAQ entries |
| `user_admin` | Manage users and roles |
| `feedback_reviewer` | View answer ratings and feedback |
| `knowledge_admin` | Manage knowledge sources and index versions |
| `system_admin` | Manage system settings |

## Running Migrations

### Locally (inside the API container or venv)

```bash
# From apps/api/
cd apps/api
alembic upgrade head
```

### Inside Docker

```bash
# One-shot migration container run
docker compose run --rm api alembic upgrade head

# Or exec into running container
docker compose exec api alembic upgrade head
```

### Downgrade

```bash
alembic downgrade -1          # one step back
alembic downgrade base        # all the way down
```

### Create a new migration (after editing models)

```bash
alembic revision --autogenerate -m "describe the change"
```

Review the generated file in `alembic/versions/` before applying.

## Seeding Required Roles

The seed script inserts all six required roles. It is idempotent — safe to run multiple times.

```bash
# Locally (DATABASE_URL must be set):
DATABASE_URL=postgresql://chathr_user:yourpassword@localhost:5432/chathr \
    python apps/api/scripts/seed_roles.py

# Inside Docker (after migrations have run):
docker compose run --rm api python scripts/seed_roles.py
```

## Authentication Fields

The `users` table includes local MVP authentication fields added in migration `0002`:

| Column | Type | Notes |
|---|---|---|
| `password_hash` | `Text`, nullable | bcrypt hash of local password. Nullable to support future SSO-only users who will not have a local password. |
| `last_login_at` | `DateTime(tz)`, nullable | Updated on each successful login. |

Local MVP auth uses JWT bearer tokens (see [docs/auth.md](auth.md)). Production SSO (organizational identity provider) is **not yet implemented** — the schema is intentionally compatible with both.

## Current Limitations

- `updated_at` columns are set at INSERT time by the DB. Auto-update on row modification requires either a PostgreSQL trigger or explicit application-level assignment. Triggers will be added in a future migration.
- `pgvector` extension is available in the container but the `vector` column type is not yet used (pending RAG implementation).
- Production SSO / external identity provider integration is not implemented — local bcrypt passwords are MVP only.
- DB integration tests are not yet wired into CI — they require a running PostgreSQL container.

## Next Planned Database Work

1. Add `updated_at` auto-update triggers
2. Add `pgvector` columns to `knowledge_sources` or a dedicated `embeddings` table
3. Wire migrations into Docker Compose startup or a dedicated init service
4. Add DB integration tests via pytest + testcontainers or docker-compose.test.yml
