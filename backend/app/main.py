"""FastAPI application factory.

Startup is fail-fast in prod (a half-alive API is worse than a dead one)
and tolerant in dev so the API can boot before docker-compose is up.
"""

import os
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
from app.stores import vector_store

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    try:
        await init_db()
        await vector_store.ensure_ready()
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
    # Fail closed on development settings in production: auth off, localhost
    # stores, open /metrics, schema auto-create, local blob storage... every
    # problem is listed at once. See app/core/prod_checks.py.
    from app.core.prod_checks import enforce_production_settings
    enforce_production_settings(settings, process="api")
    # Fail closed on the verification truth layer too: prod must not run the gate
    # on quote-match alone (NLI off). Same boot-time refusal posture as auth.
    from app.verification.gate import assert_verification_ready
    assert_verification_ready()
    _init_sentry(settings)
    # LangSmith: wire LANGCHAIN_* env so the LangGraph pipeline auto-traces.
    from app.llm.tracing import init_langsmith
    init_langsmith()
    app = FastAPI(
        title="Veriscope API",
        version=os.environ.get("APP_VERSION", "dev"),
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "prod" else None,
        redoc_url="/redoc" if settings.app_env != "prod" else None,
        openapi_url="/openapi.json" if settings.app_env != "prod" else None,
    )
    # Rate limiting + tracing + metrics all live in install_observability's
    # middleware (per-subject fixed window, tighter bucket for /pipeline). A
    # second limiter used to live here too — removed: two middlewares double the
    # Redis calls and split the budget across inconsistent keys. One source of
    # truth now.
    install_observability(app)
    # Outermost: reject oversized bodies before any parsing. Starlette spools a
    # multipart upload to a temp file BEFORE the handler's own size check runs,
    # and on Cloud Run /tmp is memory - so a large upload was an OOM vector.
    from app.core.limits import BodySizeLimit
    app.add_middleware(BodySizeLimit, max_bytes=(settings.upload_max_pdf_mb + 1) * 1024 * 1024)
    # CORS is added LAST so it is the OUTERMOST layer. Starlette wraps in reverse
    # order of registration; with CORS innermost, a 429 from the rate limiter or
    # a 413 from the size cap went out without CORS headers, and the browser
    # reported an opaque network error instead of "slow down" / "file too large".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
        expose_headers=["X-Request-Id", "Retry-After"],
        max_age=600,
    )

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

    @app.get("/livez", include_in_schema=False)
    async def livez():
        """Liveness: the process can serve a request. Checks NO dependency on
        purpose - a liveness probe that fails on a database blip makes the
        orchestrator restart every replica at once, turning a brief outage into
        a full one."""
        return {"status": "ok"}

    async def _readiness() -> JSONResponse:
        """Readiness: every dependency a request needs. 503 when any is down so
        a load balancer stops routing here (the old /health returned 200 with
        status="degraded", which no load balancer reads)."""
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
        name, state = await vector_store.health()
        deps[name] = state
        from app.stores import blob_store
        deps["blob_store"] = await blob_store.health()
        healthy = all(v == "ok" for v in deps.values())
        body = {"status": "ok" if healthy else "degraded",
                "version": os.environ.get("APP_VERSION", "dev")}
        # Dependency detail is for operators; in prod it is not echoed to the
        # internet (error strings can carry hostnames).
        if settings.app_env != "prod":
            body["env"] = settings.app_env
            body["dependencies"] = deps
        else:
            body["dependencies"] = {k: ("ok" if v == "ok" else "down") for k, v in deps.items()}
        return JSONResponse(status_code=200 if healthy else 503, content=body)

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        return await _readiness()

    # /health kept for existing probes and the deploy smoke test; /api/health so
    # the check is reachable through the web origin (nginx proxies /api only).
    @app.get("/health", include_in_schema=False)
    async def health():
        return await _readiness()

    @app.get("/api/health", include_in_schema=False)
    async def api_health():
        return await _readiness()

    app.include_router(router)
    return app


app = create_app()
