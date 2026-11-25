"""Async database engine and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Base

logger = get_logger("db")

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            echo=False,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def init_db(*, attempts: int = 10, delay: float = 2.0) -> None:
    """Ensure the database is reachable and (in dev) the schema exists.

    Schema ownership is governed by settings.db_auto_create:
      * True  (dev/test default): create_all bootstraps the schema in-process.
      * False (production):        Alembic owns the schema — `alembic upgrade
                                   head` runs in the deploy step and init_db
                                   only verifies connectivity + hot indexes,
                                   never running create_all against a
                                   migration-managed database.

    Retries on startup: containers (or Supabase) may not accept connections
    the instant a worker/API boots. A transient refusal must not kill the
    process - we back off and retry rather than crash on a cold dependency.
    """
    import asyncio

    settings = get_settings()
    engine = get_engine()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                if settings.db_auto_create:
                    await _ensure_extensions(conn)
                    await conn.run_sync(Base.metadata.create_all)
                    await _ensure_dev_columns(conn)
                else:
                    from sqlalchemy import text
                    await conn.execute(text("SELECT 1"))  # connectivity only
                await _ensure_indexes(conn)
            logger.info("database schema ensured",
                        extra={"managed_by": "create_all" if settings.db_auto_create else "alembic"})
            return
        except Exception as exc:  # connection refused, DB starting, etc.
            last_exc = exc
            logger.warning("database not ready, retrying",
                           extra={"attempt": attempt, "max": attempts,
                                  "error": str(exc)[:160]})
            await asyncio.sleep(delay)
    raise RuntimeError(
        f"database unreachable after {attempts} attempts: {str(last_exc)[:200]}"
    )


# Hot-path composite indexes. `create_all` adds indexes only for tables it
# creates fresh, so we apply these idempotently (CREATE INDEX IF NOT EXISTS)
# on every boot — covering pre-existing databases too. Cheap: a no-op once
# present. Graduates to Alembic when the schema stabilizes.
_HOT_INDEXES = (
    # runs list: filtered by project, ordered by recency.
    'CREATE INDEX IF NOT EXISTS ix_runs_project_created '
    'ON runs (project_id, created_at DESC)',
    # monitor alerts: filtered by project + status, ranked by score.
    'CREATE INDEX IF NOT EXISTS ix_alerts_project_status_score '
    'ON monitor_alerts (project_id, status, score DESC)',
    # report claim fan-in: report load batches on report_id.
    'CREATE INDEX IF NOT EXISTS ix_claims_report ON claims (report_id)',
)


async def _ensure_extensions(conn) -> None:
    """Dev bootstrap only (db_auto_create): the chunk table's vector column needs
    pgvector before create_all can build it. Production gets this from Alembic
    (0001/0007), never from the app at boot."""
    from sqlalchemy import text
    if conn.dialect.name == "postgresql":
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


# Columns added after a dev database was first created. create_all never ALTERs
# an existing table, so a laptop database that predates a column would boot and
# then fail on first use. Mirrors the Alembic revisions that add them.
_DEV_COLUMNS = (
    "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding vector(384)",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS launch_params JSON NOT NULL DEFAULT '{}'",
)


async def _ensure_dev_columns(conn) -> None:
    from sqlalchemy import text
    if conn.dialect.name != "postgresql":
        return
    for stmt in _DEV_COLUMNS:
        await conn.execute(text(stmt))
    if get_settings().vector_backend == "pgvector":
        # Keep `embedded` honest: on a database whose vectors are still in
        # Qdrant, no chunk has a pgvector vector yet. Same step as 0007.
        await conn.execute(text(
            "UPDATE chunks SET embedded = false WHERE embedding IS NULL AND embedded"))


async def _ensure_indexes(conn) -> None:
    from sqlalchemy import text
    dialect = conn.dialect.name
    if dialect != "postgresql":
        return  # IF NOT EXISTS index syntax is Postgres-specific; skip elsewhere (tests use sqlite)
    for stmt in _HOT_INDEXES:
        try:
            await conn.execute(text(stmt))
        except Exception as exc:  # never let an index failure block startup
            logger.warning("index ensure skipped", extra={"error": str(exc)[:160]})


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    get_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session
