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


def _consteq(a: str, b: str) -> bool:
    """Constant-time comparison to avoid leaking the token via timing."""
    import hmac
    return hmac.compare_digest(a, b)


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
        # API responses are JSON and load no resources — lock them down fully.
        # (The SPA's own CSP belongs on its static host, not here.)
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if elapsed > 1.0:
            logger.info(
                "slow request",
                extra={"path": route_path, "ms": round(elapsed * 1000), "status": response.status_code},
            )
        return response

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        """Per-subject fixed-window limit. Subject = the authenticated token
        (so one user can't multiply their budget by rotating IPs, and shared
        NAT/proxy IPs don't throttle each other) falling back to client IP.
        Expensive endpoints get a tighter budget. Fail-open if Redis is down."""
        # Exempt long-lived / high-frequency reads: the SSE + WS status streams
        # are ONE persistent connection (not spam), and status polling is
        # expected. Counting them made normal single-user use hit 429 and broke
        # the completion WebSocket + chat mid-flight.
        _p = request.url.path
        _exempt = _p.startswith("/api/status/") or _p.startswith("/api/health")
        if _p.startswith("/api/") and not _exempt:
            try:
                from app.core.config import get_settings
                from app.stores.redis_store import get_redis
                settings = get_settings()

                # Subject: hash of the bearer token if present, else client IP.
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    import hashlib
                    subject = "u:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
                elif settings.trust_forwarded_for and request.headers.get("x-forwarded-for"):
                    subject = "ip:" + request.headers["x-forwarded-for"].split(",")[0].strip()
                else:
                    subject = "ip:" + (request.client.host if request.client else "unknown")

                # Tighter bucket for the expensive pipeline launch.
                expensive = (request.method == "POST"
                             and request.url.path.rstrip("/").endswith("/pipeline"))
                limit = (settings.pipeline_rate_limit_per_min if expensive
                         else settings.rate_limit_per_min)
                bucket = "pipe" if expensive else "api"

                window = int(time.time() // 60)
                key = f"rl:{bucket}:{subject}:{window}"
                r = get_redis()
                n = await r.incr(key)
                if n == 1:
                    await r.expire(key, 60)
                if n > limit:
                    return Response(
                        '{"error":"rate_limited","message":"Too many requests; slow down."}',
                        status_code=429, media_type="application/json",
                        headers={"Retry-After": "60"},
                    )
            except Exception:
                pass  # fail open
        return await call_next(request)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        # If a metrics token is configured, require it (Bearer header or
        # ?token=). Prevents anonymous scraping of internal operational data.
        from app.core.config import get_settings
        token = get_settings().metrics_token
        if token:
            auth = request.headers.get("authorization", "")
            supplied = auth[7:] if auth.lower().startswith("bearer ") else \
                request.query_params.get("token", "")
            if not _consteq(supplied, token):
                return Response('{"error":"unauthorized"}', status_code=401,
                                media_type="application/json")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
