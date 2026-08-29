#!/bin/sh
# Optionally apply DB migrations before starting the process, then exec the CMD.
# Set RUN_MIGRATIONS=1 on exactly ONE service (the API, or a dedicated migrate
# job) in production so `alembic upgrade head` runs once per deploy. Pair with
# DB_AUTO_CREATE=false so Alembic is the single source of truth for the schema.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] applying database migrations: alembic upgrade head"
  alembic upgrade head
fi

exec "$@"
