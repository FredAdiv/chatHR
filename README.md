# ChatHR

A secure AI chat system for HR employees in Israeli government and civil service.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose v2)
- Git

## How to Run Locally

```bash
# 1. Clone the repository
git clone https://github.com/FredAdiv/chatHR.git
cd chatHR

# 2. Create your local env file
cp .env.example .env
# Edit .env and replace all CHANGE_ME values with real values

# 3. Start all services
docker compose up --build
```

## Service URLs

| Service | URL |
|---|---|
| Frontend (Next.js) | http://localhost:3000 |
| Backend API (FastAPI) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

## Health Checks

```bash
curl http://localhost:8000/health   # API liveness
curl http://localhost:8000/ready    # API readiness (checks DB + Redis)
```

## How to Stop / Reset Containers

```bash
# Stop services (keeps data volumes)
docker compose down

# Stop and remove all data volumes (full reset)
docker compose down -v
```

## Running Migrations

```bash
# Inside Docker (recommended):
docker compose run --rm api alembic upgrade head

# Seed required roles after migration:
docker compose run --rm api python scripts/seed_roles.py

# Create initial system_admin user (first time only):
docker compose run --rm api python -m scripts.create_initial_admin
```

## Running Tests

```bash
# Unit tests (requires pip install of API requirements)
cd apps/api
pip install -r requirements.txt
cd ../..
pytest tests/unit/
```

## Project Structure

```
apps/web/          Next.js frontend
apps/api/          FastAPI backend
packages/shared/   Shared types and utilities
ingestion/         Document crawling, parsing, and chunking
rag/               Retrieval, ranking, citation, authority
tests/             Unit, integration, and eval tests
docs/              Project documentation
```

## Documentation

- [Project Brief](docs/project-brief.md)
- [Architecture](docs/architecture.md)
- [Authentication](docs/auth.md)
- [Database](docs/database.md)
- [Claude Code Instructions](docs/claude-code-instructions.md)
- [Codex / QA Instructions](docs/codex-qa-instructions.md)

## Authentication

See [docs/auth.md](docs/auth.md) for the full auth flow. Quick start:

```bash
# Login:
curl -X POST http://localhost:8000/auth/login \
  -d "username=admin@example.com&password=yourpassword"

# Use the returned token:
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>"
```

## Current Limitations

MVP Phase 1–3 complete. The following features are **not yet implemented**:

- Chat interface and streaming
- RAG pipeline (document indexing and retrieval)
- FAQ management UI
- LLM Gateway / OpenRouter integration
- Privacy guard
- SSO / external identity provider
