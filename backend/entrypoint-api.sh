#!/bin/sh
# API container entrypoint: bring the schema up to date, then serve.
set -e

echo "Applying database migrations..."
alembic upgrade head

# Demo monitors (only if SEED_DEMO=true and the table is empty)
python -m app.seed

echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
