"""OpenTelemetry distributed tracing (optional).

Active only when OTEL_ENABLED=true AND the opentelemetry packages are
installed (backend extra: `pip install -e ".[otel]"`). Every import and export
path is defensive: a missing package or a dead collector degrades to a no-op,
so tracing can never break a request or a run.

Produces a trace tree across API request -> httpx (LLM / source calls) ->
Redis (queue) -> worker pipeline nodes, exported via OTLP/HTTP to Tempo. It
composes with Langfuse (LLM-level spans) rather than replacing it: OTel gives
the system-level waterfall, Langfuse the prompt/token detail.
"""

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("otel")

_initialized = False


def _install_provider(service_name: str) -> None:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = get_settings()
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": settings.app_env,
    })
    provider = TracerProvider(resource=resource)
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def init_otel(app=None, *, service_name: str | None = None) -> None:
    """Set up tracing + auto-instrumentation. Safe to call once per process;
    a second call is a no-op. `app` (a FastAPI instance) enables request spans;
    the worker passes None and only gets httpx/redis + manual node spans."""
    global _initialized
    settings = get_settings()
    if not settings.otel_enabled or _initialized:
        return
    name = service_name or settings.otel_service_name
    try:
        _install_provider(name)
    except Exception as exc:  # SDK/exporter missing or misconfigured
        logger.warning("otel disabled: provider init failed",
                       extra={"error": str(exc)[:160]})
        return

    # Auto-instrument each library independently so one missing package doesn't
    # sink the rest.
    for label, instrument in (
        ("httpx", _instrument_httpx),
        ("redis", _instrument_redis),
        ("fastapi", lambda: _instrument_fastapi(app)),
    ):
        try:
            instrument()
        except Exception as exc:
            logger.info("otel instrumentation skipped",
                        extra={"lib": label, "error": str(exc)[:120]})

    _initialized = True
    logger.info("opentelemetry tracing enabled",
                extra={"service": name, "endpoint": settings.otel_exporter_otlp_endpoint})


def _instrument_httpx() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    HTTPXClientInstrumentor().instrument()


def _instrument_redis() -> None:
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    RedisInstrumentor().instrument()


def _instrument_fastapi(app) -> None:
    if app is None:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)


# ── Manual spans (pipeline nodes) — work with or without OTel active ──────

class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_attribute(self, *args, **kwargs):
        pass


class _NoopTracer:
    def start_as_current_span(self, *args, **kwargs):
        return _NoopSpan()


def get_tracer(name: str = "veriscope"):
    """A real tracer when OTel is active, else a no-op with the same surface —
    callers use `with get_tracer().start_as_current_span(...)` unconditionally."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()
