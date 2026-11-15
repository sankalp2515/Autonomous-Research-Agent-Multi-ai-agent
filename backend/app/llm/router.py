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
from app.core.logging import get_logger, run_id_var
from app.core.observability import LLM_CALLS
from app.llm.clients import (
    LLMResult, call_provider, provider_configured, provider_keys, provider_rpm,
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
# ONE CHAIN, ONE ORDER, EVERY STEP: gemini -> openrouter -> groq.
#
# The per-step chains this replaces assigned providers by task complexity, and
# the fleet drifted out from under that judgement: nvidia was failing
# continuously (503s from integrate.api.nvidia.com) while sitting FIRST in six
# of the chains, so every heavy step paid a dead provider before reaching a live
# one, and deepseek answers 402 Payment Required on the current key. A chain
# entry that cannot succeed is a wasted round-trip on every call that reaches
# it.
#
# Both are OUT OF THE ROTATION, not deleted: their ProviderSpecs and settings
# remain untouched, so re-enabling either is one line in this dict.
#
# The order is uniform on purpose. Varying it per step optimises a second-order
# effect (which model writes marginally better JSON) at the cost of the
# first-order one (which model answers at all). gemini leads because it is the
# provider scaled with keys here; groq is last because it is the fallback that
# must still answer when the first two are throttled.
_CHAIN = ["gemini", "openrouter", "groq"]

ROUTING: dict[str, list[str]] = {
    "intent":          _CHAIN,
    "clarify":         _CHAIN,
    "clarify_refine":  _CHAIN,
    "query_expansion": _CHAIN,
    "query_transform": _CHAIN,
    "screening":       _CHAIN,
    "next_questions":  _CHAIN,
    "structure":       _CHAIN,
    "outline":         _CHAIN,
    "judge":           _CHAIN,
    "extract":         _CHAIN,
    "draft":           _CHAIN,
    "chat":            _CHAIN,
    "chat_rewrite":    _CHAIN,
    # Out of rotation: "nvidia" (continuous 503s), "deepseek" (402 on this key).
}
_DEFAULT_CHAIN = _CHAIN

# Latency budget for failover. The OLD design blocked up to 90s polling ONE
# provider's throttle before even trying the next — so a throttled lead provider
# added up to 90s of dead wait to every call. Now: try each provider for an
# IMMEDIATE token and fail over instantly if throttled; only if EVERY provider is
# throttled do we do a single short bounded wait. Cross-provider failover is now
# effectively instant.
_THROTTLE_SHORT_WAIT = 20  # last-resort wait when the WHOLE chain is throttled
_CALL_TIMEOUT = 150        # hard ceiling per provider call; a hang fails over
_CIRCUIT_TTL = 300         # cooldown after a hard (auth/payment) provider failure

# HTTP statuses that mean "this provider is unusable right now" (not transient).
_HARD_STATUSES = {401, 402, 403, 404}


# ── Lanes: one per (provider, API key) ──────────────────────────────────
#
# A free-tier key IS the rate limit, so four gemini keys are four times the
# throughput — but only if the router treats them as four independent things.
# Both Redis helpers below are keyed by NAME (`bucket:{name}`, `circuit:{name}`),
# so a lane name gives each key its own token bucket and its own circuit with no
# change to the store: one exhausted or revoked key says nothing about the next.
#
# Lane 0 keeps the bare provider name so existing buckets, circuits and the
# dashboard's provider view keep meaning exactly what they meant before.
def _lane(provider: str, key_index: int) -> str:
    return provider if key_index == 0 else f"{provider}#{key_index}"


# Where each provider's key search STARTS. Process-local on purpose: the token
# buckets in Redis are what enforce fairness across workers, and this only has
# to stop every concurrent call in this process from stampeding key 0, failing
# to acquire, and cascading down the same order together.
_cursor: dict[str, int] = {}


def _lanes_for(provider: str) -> list[tuple[str, int]]:
    n = len(provider_keys(provider))
    if n <= 1:
        return [(provider, 0)]
    start = _cursor.get(provider, 0)
    _cursor[provider] = (start + 1) % n
    return [(provider, (start + i) % n) for i in range(n)]


def _cache_key(step: str, prompt: str, system: str) -> str:
    h = hashlib.sha256(f"{step}\x00{system}\x00{prompt}".encode()).hexdigest()
    return f"{step}:{h}"


def _is_hard_failure(exc: Exception) -> bool:
    """A hard failure trips the provider's circuit (skip it for a cooldown) so an
    unfunded/misconfigured provider stops taxing every call with a wasted RTT."""
    import httpx
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _HARD_STATUSES
    # A payment/auth message surfaced as ExternalServiceError also counts.
    msg = str(exc).lower()
    return any(s in msg for s in ("payment required", "402", "unauthorized", "invalid api key"))


async def complete(step: str, prompt: str, *, system: str = "",
                   temperature: float = 0.2, max_tokens: int = 4096,
                   use_cache: bool = True, exclude: set[str] | None = None) -> LLMResult:
    """`exclude` drops providers from the chain for this call — used by the JSON
    repair path to retry on a DIFFERENT provider than the one that just emitted
    unparseable output (a provider that's up but bad at JSON would otherwise be
    handed the same failing task again)."""
    settings = get_settings()
    key = _cache_key(step, prompt, system)
    if use_cache:
        cached = await redis_store.cache_get(key)
        if cached is not None:
            LLM_CALLS.labels("cache", step, "hit").inc()
            return LLMResult(cached, "cache")

    exclude = exclude or set()
    chain = [p for p in ROUTING.get(step, _DEFAULT_CHAIN)
             if provider_configured(p) and p not in exclude]
    # If excluding leaves nothing configured, fall back to the full chain — a
    # repair on the same provider still beats failing outright.
    if not chain and exclude:
        chain = [p for p in ROUTING.get(step, _DEFAULT_CHAIN) if provider_configured(p)]
    if not chain:
        raise ExternalServiceError(
            f"no LLM provider configured for step '{step}' - add at least one API key"
        )

    # Expand each provider into its LANES, dropping the ones whose circuit is
    # open. A dead KEY removes only its own lane; the provider keeps serving on
    # the others.
    lanes: list[tuple[str, int]] = []
    for provider in chain:
        for prov, idx in _lanes_for(provider):
            if not await redis_store.circuit_open(_lane(prov, idx)):
                lanes.append((prov, idx))
    # Everything cooling at once: try anyway rather than fail outright — a long
    # shot beats a refusal.
    if not lanes:
        lanes = [lane for p in chain for lane in _lanes_for(p)]

    last_error: Exception | None = None

    async def _try(provider: str, key_index: int) -> LLMResult | None:
        """One attempt on one lane (token already acquired). Returns the result,
        or None after recording the failure + tripping the LANE's circuit on a
        hard error. Never raises."""
        nonlocal last_error
        lane = _lane(provider, key_index)
        t0 = time.perf_counter()
        try:
            logger.info("llm call start",
                        extra={"provider": provider, "lane": lane, "step": step})
            result = await asyncio.wait_for(
                call_provider(provider, prompt, system=system,
                              temperature=temperature, max_tokens=max_tokens,
                              key_index=key_index),
                timeout=_CALL_TIMEOUT,
            )
            elapsed = round((time.perf_counter() - t0) * 1000)
            logger.info("llm call ok", extra={
                "provider": provider, "lane": lane, "step": step, "ms": elapsed,
                "tokens_in": result.tokens_in, "tokens_out": result.tokens_out})
            from app.llm.tracing import trace_generation
            trace_generation(step, provider, prompt, result.text,
                             result.tokens_in, result.tokens_out, elapsed)
            LLM_CALLS.labels(provider, step, "ok").inc()
            # Durable per-run token accounting (the dashboard's cost view reads
            # this; run_id comes from the pipeline's context var, "-" for chat).
            await redis_store.incr_run_tokens(
                run_id_var.get(), result.tokens_in, result.tokens_out)
            if use_cache:
                await redis_store.cache_set(key, result.text, settings.llm_cache_ttl_seconds)
            return result
        except asyncio.TimeoutError:
            last_error = TimeoutError(f"{lane} exceeded {_CALL_TIMEOUT}s")
            LLM_CALLS.labels(provider, step, "timeout").inc()
            logger.warning("llm call TIMEOUT, falling through chain",
                           extra={"provider": provider, "lane": lane, "step": step})
        except Exception as exc:  # provider failed after its own retries
            last_error = exc
            LLM_CALLS.labels(provider, step, "error").inc()
            hard = _is_hard_failure(exc)
            if hard:
                # THE LANE, NOT THE PROVIDER. 401/402 are facts about ONE
                # credential; cooling all four gemini keys because one was
                # revoked would throw away three working ones.
                await redis_store.trip_circuit(lane, ttl=_CIRCUIT_TTL)
            logger.warning("provider failed, falling through chain", extra={
                "provider": provider, "lane": lane, "step": step, "hard": hard,
                "error": str(exc)[:200]})
        return None

    # PASS 1 — immediate: try each LANE that has a token RIGHT NOW, failing over
    # instantly on throttle instead of blocking on the first one. With nine
    # lanes configured, an exhausted gemini key falls through to the next gemini
    # key before it ever reaches openrouter.
    throttled: list[tuple[str, int]] = []
    for provider, key_index in lanes:
        if not await redis_store.acquire_token(_lane(provider, key_index),
                                               provider_rpm(provider)):
            throttled.append((provider, key_index))
            continue
        result = await _try(provider, key_index)
        if result is not None:
            return result

    # PASS 2 — last resort: every lane was throttled (or every attempt failed).
    # Wait a SHORT bounded time for one of them to free a token.
    deadline = time.monotonic() + _THROTTLE_SHORT_WAIT
    while throttled and time.monotonic() < deadline:
        for provider, key_index in list(throttled):
            if await redis_store.acquire_token(_lane(provider, key_index),
                                               provider_rpm(provider)):
                result = await _try(provider, key_index)
                if result is not None:
                    return result
                throttled.remove((provider, key_index))  # tried; don't re-wait
        await asyncio.sleep(1.0)

    raise ExternalServiceError(
        f"all providers in chain failed for step '{step}'",
        detail={"chain": chain, "lanes": len(lanes),
                "last_error": str(last_error)[:300]},
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
    # The same key `complete` caches under, so this layer can evict a poisoned
    # entry and write back the output that actually parsed.
    key = _cache_key(step, prompt, full_system)
    result = await complete(step, prompt, system=full_system,
                            temperature=temperature, max_tokens=max_tokens)
    try:
        return schema.model_validate(extract_json(result.text))
    except (ValueError, ValidationError) as first_err:
        # A POISONED CACHE ENTRY IS WORSE THAN NO CACHE, and this one could not
        # heal itself. `complete` writes `result.text` to the cache the moment a
        # provider returns it - BEFORE anything checks that it parses - so a
        # malformed response is stored under the prompt's key and served for the
        # full TTL. Every later call then pays MORE than an uncached one: a
        # cache read, a failed parse, and a full repair chain. Observed live on
        # step=screen: the entry came back as provider=cache, failed to parse,
        # and the repair went to a provider that was down - 126 seconds on a 503
        # before failing over, turning a "cached" screening call into a
        # 129-second request that could never get faster.
        #
        # So the bad entry is evicted here, and the repaired output is written
        # under the ORIGINAL key below. The next identical call is a clean hit.
        if result.provider == "cache":
            await redis_store.cache_delete(key)
        logger.info("json repair attempt", extra={
            "step": step, "provider": result.provider, "error": str(first_err)[:200]})
        repair_prompt = (
            "Your previous output failed validation.\n"
            f"Error: {str(first_err)[:500]}\n"
            f"Previous output: {result.text[:3000]}\n"
            "Return ONLY corrected JSON matching the schema."
        )
        # Prefer a DIFFERENT provider for the repair: a cached result has
        # provider "cache" (nothing to exclude); a live one excludes the model
        # that just produced unparseable JSON.
        exclude = {result.provider} if result.provider not in ("cache", "") else None
        repair = await complete(step, repair_prompt, system=full_system,
                                temperature=0.0, max_tokens=max_tokens,
                                use_cache=False, exclude=exclude)
        try:
            parsed = schema.model_validate(extract_json(repair.text))
        except (ValueError, ValidationError) as second_err:
            raise ExternalServiceError(
                f"step '{step}' produced unparseable output after repair",
                detail={"error": str(second_err)[:300]},
            ) from second_err
        # Cache what actually VALIDATED, under the original prompt's key, so a
        # repair is paid for once instead of on every future identical call.
        try:
            await redis_store.cache_set(key, repair.text,
                                        get_settings().llm_cache_ttl_seconds)
        except Exception:
            pass
        return parsed
