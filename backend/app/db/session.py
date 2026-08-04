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
    """Create tables if absent. For Supabase, the same DDL applies via
    DATABASE_URL; migrations graduate to Alembic when the schema stabilizes.

    Retries on startup: containers (or Supabase) may not accept connections
    the instant a worker/API boots. A transient refusal must not kill the
    process - we back off and retry rather than crash on a cold dependency.
    """
    import asyncio

    engine = get_engine()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await _ensure_indexes(conn)
            logger.info("database schema ensured")
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
