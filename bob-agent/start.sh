#!/bin/bash
# Unified entrypoint for bob-agent (web) and bob-worker (ARQ).
# Set START_MODE=worker in the Railway worker service env vars to run the ARQ worker.
# Default (no START_MODE) runs the FastAPI web service with migrations.
set -e

if [ "${START_MODE:-agent}" = "worker" ]; then
    echo "Starting ARQ worker..."
    exec arq app.worker.WorkerSettings
else
    echo "Running database migrations..."
    alembic upgrade head
    echo "Starting uvicorn on port ${PORT:-8000}..."
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi
