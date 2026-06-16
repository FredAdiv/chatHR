#!/bin/sh
set -e
echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head
echo "[entrypoint] Migrations complete. Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
