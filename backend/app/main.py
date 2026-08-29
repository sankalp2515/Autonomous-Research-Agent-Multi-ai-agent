"""FastAPI application factory.

Startup is fail-fast in prod (a half-alive API is worse than a dead one)
and tolerant in dev so the API can boot before docker-compose is up.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.core.observability import install_observability
from app.db.session import init_db
from app.stores.qdrant_store import ensure_collection

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    try:
        await init_db()
        await ensure_collection()
    except Exception:
        if settings.app_env == "prod":
            raise
        logger.exception("infrastructure not ready (dev mode: continuing; "
                         "start docker-compose for full functionality)")
    logger.info("api started", extra={"env": settings.app_env})
    yield
    logger.info("api stopped")


def _init_sentry(settings) -> None:
    """Wire Sentry error tracking if SENTRY_DSN is set. No-op otherwise."""
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env,
                        traces_sample_rate=0.1)
        logger.info("sentry initialised")
    except Exception:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed (pip install sentry-sdk)")


def create_app() -> FastAPI:
    settings = get_settings()
    # Fail closed: a production deployment must never run with auth disabled.
    # This turns the single worst footgun (open API because AUTH_DISABLED was
    # left at its dev default) into a loud boot-time refusal.
    if settings.app_env == "prod" and settings.auth_disabled:
        raise RuntimeError(
            "AUTH_DISABLED=true is not permitted when APP_ENV=prod — refusing to "
            "start an unauthenticated API. Set AUTH_DISABLED=false and configure "
            "SUPABASE_URL."
        )
    # Fail closed on the verification truth layer too: prod must not run the gate
    # on quote-match alone (NLI off). Same boot-time refusal posture as auth.
    from app.verification.gate import assert_verification_ready
    assert_verification_ready()
    # Invite emails would link to localhost if app_base_url isn't set for prod.
    if (settings.app_env == "prod" and settings.smtp_host
            and "localhost" in settings.app_base_url):
        logger.warning("APP_BASE_URL is still localhost while SMTP is configured — "
                       "invite emails will link to localhost. Set APP_BASE_URL.")
    _init_sentry(settings)
    # LangSmith: wire LANGCHAIN_* env so the LangGraph pipeline auto-traces.
    from app.llm.tracing import init_langsmith
    init_langsmith()
    app = FastAPI(
        title="Grounded Research Assistant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "prod" else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Rate limiting + tracing + metrics all live in install_observability's
    # middleware (per-subject fixed window, tighter bucket for /pipeline). A
    # second limiter used to live here too — removed: two middlewares double the
    # Redis calls and split the budget across inconsistent keys. One source of
    # truth now.
    install_observability(app)

    # OpenTelemetry request/httpx/redis spans (no-op unless OTEL_ENABLED).
    from app.core.otel import init_otel
    init_otel(app, service_name="veriscope-api")

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        body = {"error": exc.code, "message": exc.message}
        if settings.app_env != "prod":
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status, content=body)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled error", extra={"path": request.url.path})
        body = {"error": "internal_error", "message": "internal server error"}
        if settings.app_env != "prod":
            body["message"] = str(exc)[:500]
        return JSONResponse(status_code=500, content=body)

    @app.get("/health", include_in_schema=False)
    async def health():
        # Deep health: check each dependency so orchestration can tell a
        # half-alive API from a healthy one. Never raises - reports per-dep.
        deps: dict[str, str] = {}
        try:
            from sqlalchemy import text
            from app.db.session import session_scope
            async with session_scope() as s:
                await s.execute(text("SELECT 1"))
            deps["postgres"] = "ok"
        except Exception as exc:
            deps["postgres"] = f"down: {str(exc)[:80]}"
        try:
            from app.stores.redis_store import get_redis
            await get_redis().ping()
            deps["redis"] = "ok"
        except Exception as exc:
            deps["redis"] = f"down: {str(exc)[:80]}"
        try:
            from app.stores.qdrant_store import get_qdrant
            await get_qdrant().get_collections()
            deps["qdrant"] = "ok"
        except Exception as exc:
            deps["qdrant"] = f"down: {str(exc)[:80]}"
        healthy = all(v == "ok" for v in deps.values())
        return {"status": "ok" if healthy else "degraded",
                "env": settings.app_env, "dependencies": deps}

    app.include_router(router)
    return app


app = create_app()
