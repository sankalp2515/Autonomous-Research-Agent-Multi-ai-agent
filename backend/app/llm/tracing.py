"""Optional Langfuse LLM tracing.

Enabled only when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set. Fully
defensive: a missing package or any SDK error is a silent no-op, so tracing
never affects the request path. Gives per-call cost/latency/quality traces in
the Langfuse dashboard on top of the Prometheus counters.
"""

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("tracing")


@lru_cache(maxsize=1)
def _client():
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse
        logger.info("langfuse tracing enabled")
        return Langfuse(public_key=s.langfuse_public_key,
                        secret_key=s.langfuse_secret_key, host=s.langfuse_host)
    except Exception:
        logger.warning("LANGFUSE keys set but langfuse not installed (pip install langfuse)")
        return None


def trace_generation(step: str, provider: str, prompt: str, output: str,
                     tokens_in: int, tokens_out: int, ms: int) -> None:
    c = _client()
    if c is None:
        return
    try:
        c.generation(name=step, model=provider, input=prompt[:4000],
                     output=output[:4000],
                     usage={"input": tokens_in, "output": tokens_out},
                     metadata={"latency_ms": ms, "provider": provider})
    except Exception:
        pass  # tracing must never break a request
