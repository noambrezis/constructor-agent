#!/bin/bash
# Startup script for bob-agent Railway service.
# Runs Alembic migrations before launching uvicorn so the schema is always
# up-to-date on every deploy.
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
