"""Observability: request tracing middleware + Prometheus metrics.

Counters and histograms answer the operational questions that matter for
this system specifically: how often does the gate reject claims, how many
LLM calls does a run cost, where does pipeline time go.
"""

import time
import uuid

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from app.core.logging import get_logger, request_id_var

logger = get_logger("http")

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
LLM_CALLS = Counter(
    "llm_calls_total", "LLM calls", ["provider", "step", "outcome"]
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "LLM tokens used", ["provider", "direction"]
)
GATE_CLAIMS = Counter(
    "gate_claims_total", "Claims processed by the verification gate",
    ["outcome"],  # verified | failed_quote | failed_nli | failed_citation
)
PIPELINE_NODE_SECONDS = Histogram(
    "pipeline_node_seconds", "Pipeline node duration", ["node"],
    buckets=(0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)
INGEST_DOCS = Counter(
    "ingest_documents_total", "Documents ingested", ["source_type", "outcome"]
)


RATE_LIMIT_PER_MIN = 150  # per-IP API request budget per minute


def install_observability(app: FastAPI) -> None:
    @app.middleware("http")
    async def trace_requests(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(request.method, request.url.path, "500").inc()
            logger.exception("request failed", extra={"path": request.url.path})
            raise
        finally:
            request_id_var.reset(token)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route_path).observe(elapsed)
        response.headers["x-request-id"] = request_id
        # Security headers on every response (defense-in-depth).
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if elapsed > 1.0:
            logger.info(
                "slow request",
                extra={"path": route_path, "ms": round(elapsed * 1000), "status": response.status_code},
            )
        return response

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        """Per-IP fixed-window limit on the API. Fail-open if Redis is down -
        availability beats strict limiting for a research tool."""
        if request.url.path.startswith("/api/"):
            try:
                from app.stores.redis_store import get_redis
                ip = request.client.host if request.client else "unknown"
                key = f"rl:{ip}:{int(time.time() // 60)}"
                r = get_redis()
                n = await r.incr(key)
                if n == 1:
                    await r.expire(key, 60)
                if n > RATE_LIMIT_PER_MIN:
                    return Response(
                        '{"error":"rate_limited","message":"Too many requests; slow down."}',
                        status_code=429, media_type="application/json",
                    )
            except Exception:
                pass  # fail open
        return await call_next(request)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
