# ChatHR

A secure AI chat system for HR employees in Israeli government and civil service.

## Quick Start

```bash
cp .env.example .env
# Fill in .env with real values
docker compose up --build
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Documentation

- [Project Brief](docs/project-brief.md)
- [Architecture](docs/architecture.md)
- [Claude Code Instructions](docs/claude-code-instructions.md)
- [Codex / QA Instructions](docs/codex-qa-instructions.md)

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

## Requirements

- Docker Desktop
- Docker Compose v2

No external cloud services required for local development.
