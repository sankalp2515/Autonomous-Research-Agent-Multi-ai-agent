"""LLM router: the only entry point the rest of the system uses.

Responsibilities, in order:
1. Cache lookup (prompt-hash, Redis) - regens and re-runs are free.
2. Token-bucket throttle honoring free-tier RPM; waits, never violates.
3. Primary provider per step (see ROUTING), fallback to the other on
   429/outage. Schemas are identical on both sides by construction.
4. Schema-validated JSON mode with one repair retry - weak free models
   are mitigated structurally, not trusted.
"""

import asyncio
import hashlib
import json
import time
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.core.observability import LLM_CALLS
from app.llm.clients import (
    LLMResult, call_provider, provider_configured, provider_rpm,
)
from app.stores import redis_store

logger = get_logger("llm.router")

T = TypeVar("T", bound=BaseModel)

# Step -> ordered fallback chain, assigned by task complexity.
#
# Tier rationale (free-tier fleet):
#   groq (llama-3.3-70b)  - fastest; cheap classification & expansion
#   gemini (flash-lite)   - good instruction following; mid-complexity JSON
#   deepseek / openrouter - stronger reasoning BUT both require account
#                           credit (verified 402 Payment Required on the
#                           current keys). Kept as TRAILING fallbacks so
#                           they auto-activate once funded, without adding a
#                           failed round-trip to every call meanwhile.
#
# Unconfigured providers are skipped at runtime; providers that error fall
# through. Effective live fleet today: gemini + groq.
ROUTING: dict[str, list[str]] = {
    # Low complexity: speed wins.
    "intent":          ["groq", "gemini"],
    "clarify":         ["groq", "gemini", "openrouter"],
    "clarify_refine":  ["groq", "gemini", "openrouter"],
    "query_expansion": ["groq", "gemini", "openrouter"],
    "screening":       ["gemini", "groq", "openrouter"],
    # Mid complexity: structure quality matters.
    "outline":         ["gemini", "groq", "deepseek", "openrouter"],
    "judge":           ["gemini", "groq", "deepseek"],
    # High complexity: reasoning quality wins; verification gate backstops all.
    # (Lead with gemini until deepseek/openrouter are funded, then promote.)
    "draft":           ["gemini", "groq", "deepseek", "openrouter"],
    "chat":            ["gemini", "groq", "deepseek", "openrouter"],
}
_DEFAULT_CHAIN = ["gemini", "groq", "deepseek", "openrouter"]

_THROTTLE_MAX_WAIT = 90  # seconds to wait for a free-tier token before failing over
_CALL_TIMEOUT = 150      # hard ceiling per provider call; a hang fails over, never stalls


def _cache_key(step: str, prompt: str, system: str) -> str:
    h = hashlib.sha256(f"{step}\x00{system}\x00{prompt}".encode()).hexdigest()
    return f"{step}:{h}"


async def _await_token(provider: str) -> bool:
    rpm = provider_rpm(provider)
    waited = 0.0
    while waited < _THROTTLE_MAX_WAIT:
        if await redis_store.acquire_token(provider, rpm):
            return True
        await asyncio.sleep(2.0)
        waited += 2.0
    return False


async def complete(step: str, prompt: str, *, system: str = "",
                   temperature: float = 0.2, max_tokens: int = 4096,
                   use_cache: bool = True) -> LLMResult:
    settings = get_settings()
    key = _cache_key(step, prompt, system)
    if use_cache:
        cached = await redis_store.cache_get(key)
        if cached is not None:
            LLM_CALLS.labels("cache", step, "hit").inc()
            return LLMResult(cached, "cache")

    chain = [p for p in ROUTING.get(step, _DEFAULT_CHAIN) if provider_configured(p)]
    if not chain:
        raise ExternalServiceError(
            f"no LLM provider configured for step '{step}' - add at least one API key"
        )
    last_error: Exception | None = None
    for provider in chain:
        logger.info("llm awaiting throttle", extra={"provider": provider, "step": step})
        if not await _await_token(provider):
            logger.warning("throttle wait exhausted",
                           extra={"provider": provider, "step": step})
            continue
        t0 = time.perf_counter()
        try:
            logger.info("llm call start", extra={"provider": provider, "step": step})
            # Hard ceiling so a hung connection can never stall a node forever -
            # it fails over to the next provider instead. This is the safety net
            # behind the 'stuck at clarify' symptom: a hang becomes a logged
            # timeout + failover, never silence.
            result = await asyncio.wait_for(
                call_provider(provider, prompt, system=system,
                              temperature=temperature, max_tokens=max_tokens),
                timeout=_CALL_TIMEOUT,
            )
            elapsed = round((time.perf_counter() - t0) * 1000)
            logger.info("llm call ok", extra={
                "provider": provider, "step": step, "ms": elapsed,
                "tokens_in": result.tokens_in, "tokens_out": result.tokens_out})
            from app.llm.tracing import trace_generation
            trace_generation(step, provider, prompt, result.text,
                             result.tokens_in, result.tokens_out, elapsed)
            LLM_CALLS.labels(provider, step, "ok").inc()
            if use_cache:
                await redis_store.cache_set(key, result.text, settings.llm_cache_ttl_seconds)
            return result
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"{provider} exceeded {_CALL_TIMEOUT}s")
            LLM_CALLS.labels(provider, step, "timeout").inc()
            logger.warning("llm call TIMEOUT, falling through chain", extra={
                "provider": provider, "step": step,
                "ms": round((time.perf_counter() - t0) * 1000)})
        except Exception as exc:  # provider failed after its own retries
            last_error = exc
            LLM_CALLS.labels(provider, step, "error").inc()
            logger.warning("provider failed, falling through chain", extra={
                "provider": provider, "step": step,
                "ms": round((time.perf_counter() - t0) * 1000),
                "error": str(exc)[:200]})
    raise ExternalServiceError(
        f"all providers in chain failed for step '{step}'",
        detail={"chain": chain, "last_error": str(last_error)[:300]},
    )


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Free models wrap JSON in prose/fences; recover it defensively."""
    candidates = [m.strip() for m in _JSON_BLOCK.findall(text)]
    candidates.append(text.strip())
    # Last resort: the largest {...} or [...] region.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError("no parseable JSON in model output")


async def complete_json(step: str, prompt: str, schema: type[T], *,
                        system: str = "", temperature: float = 0.1,
                        max_tokens: int = 4096) -> T:
    """JSON-mode completion validated against a pydantic schema, with one
    structured repair attempt before giving up."""
    schema_hint = json.dumps(schema.model_json_schema(), indent=None)
    full_system = (
        (system + "\n\n" if system else "")
        + "Respond with ONLY a JSON object matching this JSON schema. "
        + "No markdown, no commentary.\nSchema: " + schema_hint
    )
    result = await complete(step, prompt, system=full_system,
                            temperature=temperature, max_tokens=max_tokens)
    try:
        return schema.model_validate(extract_json(result.text))
    except (ValueError, ValidationError) as first_err:
        logger.info("json repair attempt", extra={"step": step, "error": str(first_err)[:200]})
        repair_prompt = (
            "Your previous output failed validation.\n"
            f"Error: {str(first_err)[:500]}\n"
            f"Previous output: {result.text[:3000]}\n"
            "Return ONLY corrected JSON matching the schema."
        )
        repair = await complete(step, repair_prompt, system=full_system,
                                temperature=0.0, max_tokens=max_tokens, use_cache=False)
        try:
            return schema.model_validate(extract_json(repair.text))
        except (ValueError, ValidationError) as second_err:
            raise ExternalServiceError(
                f"step '{step}' produced unparseable output after repair",
                detail={"error": str(second_err)[:300]},
            ) from second_err
