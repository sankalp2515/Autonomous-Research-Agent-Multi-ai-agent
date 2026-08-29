"""Optional LLM tracing — Langfuse and/or LangSmith.

Enabled per-backend only when its keys are set. Fully defensive: a missing
package or any SDK error is a silent no-op, so tracing never affects the request
path. On top of the Prometheus counters this gives per-call cost/latency/quality
traces, and — because we run a LangGraph pipeline — LangSmith also captures the
node-level run tree once `init_langsmith()` wires the LANGCHAIN_* env vars.

Pick ONE of Langfuse / LangSmith; running both just double-reports.
"""

import os
import time
from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger, run_id_var

logger = get_logger("tracing")


# ── Langfuse ─────────────────────────────────────────────────────────────
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


# ── LangSmith ────────────────────────────────────────────────────────────
def init_langsmith() -> None:
    """Wire LangSmith at startup. Setting the LANGCHAIN_* env vars makes the
    LangGraph pipeline emit its node-level run tree to LangSmith automatically
    (langchain-core reads these). No-op unless a key is configured. Call once
    from each process entry point (API + worker), before the graph runs."""
    s = get_settings()
    if not s.langsmith_api_key:
        return
    # Only set if not already set, so an explicit env override always wins.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", s.langsmith_api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", s.langsmith_project)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", s.langsmith_endpoint)
    logger.info("langsmith tracing enabled", extra={"project": s.langsmith_project})


@lru_cache(maxsize=1)
def _langsmith_enabled() -> bool:
    return bool(get_settings().langsmith_api_key)


def _langsmith_log(step: str, provider: str, prompt: str, output: str,
                   tokens_in: int, tokens_out: int, ms: int) -> None:
    """Log one finished LLM call as a LangSmith run. Our LLM calls are raw httpx
    (not LangChain), so they aren't auto-traced — we post them explicitly, tagged
    with the run_id so they correlate with the LangGraph node tree."""
    if not _langsmith_enabled():
        return
    try:
        from langsmith.run_trees import RunTree
        now = time.time()
        rt = RunTree(
            name=f"llm.{step}",
            run_type="llm",
            inputs={"prompt": prompt[:4000]},
            project_name=get_settings().langsmith_project,
            start_time=_dt(now - ms / 1000.0),
            tags=[f"provider:{provider}", f"run:{run_id_var.get()}", f"step:{step}"],
            extra={"metadata": {"provider": provider, "latency_ms": ms,
                                "tokens_in": tokens_in, "tokens_out": tokens_out}},
        )
        rt.end(outputs={"output": output[:4000]}, end_time=_dt(now))
        rt.post()
    except Exception:
        pass  # tracing must never break a request


def _dt(epoch: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def trace_generation(step: str, provider: str, prompt: str, output: str,
                     tokens_in: int, tokens_out: int, ms: int) -> None:
    # Langfuse.
    c = _client()
    if c is not None:
        try:
            c.generation(name=step, model=provider, input=prompt[:4000],
                         output=output[:4000],
                         usage={"input": tokens_in, "output": tokens_out},
                         metadata={"latency_ms": ms, "provider": provider})
        except Exception:
            pass  # tracing must never break a request
    # LangSmith.
    _langsmith_log(step, provider, prompt, output, tokens_in, tokens_out, ms)
