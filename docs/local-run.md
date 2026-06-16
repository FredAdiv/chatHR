# ChatHR — Local Development Setup

## Prerequisites

- **Docker Desktop** installed and running ([download](https://www.docker.com/products/docker-desktop/))
- Git

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/FredAdiv/chatHR.git
cd chatHR
```

### 2. Create your local `.env` file

```bash
cp .env.example .env
```

The `.env.example` contains safe dev placeholders that work out of the box.
Do not commit `.env` — it is gitignored.

### 3. Start all services

```bash
docker compose up --build
```

First build may take a few minutes while Docker pulls images and builds the API/web containers.

### 4. Open the app

| Service | URL |
|---|---|
| Frontend (chat UI) | http://localhost:3000 |
| API (FastAPI) | http://localhost:8000 |
| API health check | http://localhost:8000/health |
| MinIO console | http://localhost:9001 (user: `minioadmin`, password: `minioadmin`) |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

### 5. Verify the API is healthy

```bash
curl http://localhost:8000/health
```

Expected response: `{"status": "ok", ...}`

## Notes

- **No real secrets in `.env.example`** — all values are safe dev placeholders.
- The `OPENROUTER_API_KEY` is not needed unless you switch `LLM_PROVIDER=openrouter`.
- The symlink warning (`project loaded from symlink without explicit name`) is harmless.
- The app runs with `LLM_PROVIDER=fake-local` and `EMBEDDING_PROVIDER=fake-local` by default — no external AI calls in dev.

## Stopping services

```bash
docker compose down
```

To also remove volumes (wipes DB and MinIO data):

```bash
docker compose down -v
```
