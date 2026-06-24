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
            pool_size=10,
            max_overflow=20,
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
