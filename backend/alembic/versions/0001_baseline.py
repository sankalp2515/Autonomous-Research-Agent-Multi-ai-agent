"""baseline — adopt Alembic over the existing create_all schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-08

This is the migration baseline for a project that previously created its schema
with Base.metadata.create_all. Its upgrade() creates the FULL current schema
idempotently (checkfirst=True), so:

  * A FRESH database:      `alembic upgrade head`   → creates everything.
  * An EXISTING database   (already built by create_all): run
                           `alembic stamp 0001_baseline`  once, to record the
                           baseline as applied WITHOUT re-creating anything.

From here on, every schema change is a NEW revision:
  `alembic revision --autogenerate -m "add X"`  →  review  →  `alembic upgrade head`.
"""
from alembic import op

from app.db.models import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# Hot-path indexes that create_all can't express declaratively (mirrors
# app/db/session.py::_HOT_INDEXES) — applied idempotently here too.
_HOT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_runs_project_created ON runs (project_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_alerts_project_status_score ON monitor_alerts (project_id, status, score DESC)",
    "CREATE INDEX IF NOT EXISTS ix_claims_report ON claims (report_id)",
)


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst: only create tables/indexes that are missing, so this is safe
    # to run against a partially-populated database.
    Base.metadata.create_all(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        from sqlalchemy import text
        for stmt in _HOT_INDEXES:
            bind.execute(text(stmt))


def downgrade() -> None:
    # A baseline has no meaningful "down" — dropping the whole schema is the
    # only inverse, and that is intentionally destructive, so we refuse it.
    raise RuntimeError("the baseline migration cannot be downgraded")
