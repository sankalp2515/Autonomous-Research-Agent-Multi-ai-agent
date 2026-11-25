"""Thin HTTP clients for the free-tier providers.

Groq, DeepSeek and OpenRouter all speak the OpenAI chat-completions
dialect, so they share one transport; Gemini has its own. Raw httpx
instead of vendor SDKs: identical interfaces, full control over
timeouts/retries, and the fallback chain above treats all uniformly.
"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError, RateLimitedError
from app.core.logging import get_logger
from app.core.observability import LLM_TOKENS
from app.core.retry import retry_llm

logger = get_logger("llm.clients")

# read=65 (was 120) so that TWO attempts plus backoff fit inside the router's
# 150s per-provider ceiling — see the note on `retry_llm`. A completion that has
# produced nothing in 65s is hung, not slow: the free fleet returns a 4096-token
# draft well inside that, and failing over to another provider beats waiting.
_TIMEOUT = httpx.Timeout(connect=10, read=65, write=30, pool=10)


class LLMResult:
    def __init__(self, text: str, provider: str, tokens_in: int = 0, tokens_out: int = 0):
        self.text = text
        self.provider = provider
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str          # OpenAI-compatible chat completions URL ("" = Gemini)
    api_key_setting: str   # Settings attribute holding the key
    model_setting: str     # Settings attribute holding the model id
    rpm_setting: str       # Settings attribute holding the RPM budget


PROVIDERS: dict[str, ProviderSpec] = {
    # Vertex has no API key; its "key" slot is the project id, which is what
    # makes it configured. Auth happens per call with ADC (see _vertex_token).
    "vertex": ProviderSpec("vertex", "", "vertex_project", "vertex_model", "vertex_rpm"),
    "gemini": ProviderSpec("gemini", "", "gemini_api_key", "gemini_model", "gemini_rpm"),
    "groq": ProviderSpec(
        "groq", "https://api.groq.com/openai/v1/chat/completions",
        "groq_api_key", "groq_model", "groq_rpm",
    ),
    "deepseek": ProviderSpec(
        "deepseek", "https://api.deepseek.com/chat/completions",
        "deepseek_api_key", "deepseek_model", "deepseek_rpm",
    ),
    "openrouter": ProviderSpec(
        "openrouter", "https://openrouter.ai/api/v1/chat/completions",
        "openrouter_api_key", "openrouter_model", "openrouter_rpm",
    ),
    "nvidia": ProviderSpec(
        "nvidia", "https://integrate.api.nvidia.com/v1/chat/completions",
        "nvidia_api_key", "nvidia_model", "nvidia_rpm",
    ),
}


def provider_keys(name: str) -> list[str]:
    """Every API key configured for this provider, primary first.

    Duplicates are dropped: two lanes sharing one real key would each be given a
    full token bucket and together overrun the provider's actual limit, which
    turns a copy-paste in .env into a 429 storm. Order is stable so lane 0 is
    always the primary key.
    """
    settings = get_settings()
    spec = PROVIDERS[name]
    raw = [getattr(settings, spec.api_key_setting, "")]
    raw += [getattr(settings, f"{spec.api_key_setting}_{n}", "") for n in (2, 3, 4)]
    seen: set[str] = set()
    keys: list[str] = []
    for k in raw:
        k = (k or "").strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def provider_configured(name: str) -> bool:
    return bool(provider_keys(name))


def provider_rpm(name: str) -> int:
    """RPM budget PER KEY — the provider enforces its limit per key, so N keys
    give N buckets of this size rather than N shares of one."""
    spec = PROVIDERS[name]
    return int(getattr(get_settings(), spec.rpm_setting))


def _gemini_answer_text(data: dict, provider: str, max_tokens: int) -> str:
    """The answer text of a generateContent response (AI Studio and Vertex
    share the schema)."""
    try:
        candidate = data["candidates"][0]
        parts = candidate["content"]["parts"]
    except (KeyError, IndexError) as exc:
        raise ExternalServiceError(
            f"{provider} returned no candidates",
            detail={"finish": str(data.get("candidates", [{}])[:1])[:300]},
        ) from exc
    # ONE ANSWER CAN ARRIVE IN SEVERAL PARTS. This read `parts[0]` only, and
    # Gemini splits a single response across parts with finishReason=STOP
    # (measured: [4946, 37] and [93, 1887] characters on two screening calls).
    # Everything after the first part was dropped, the JSON no longer parsed,
    # and the repair rebuilt it from a fragment — silently losing the tail of
    # every split response at every step that uses Gemini. Thought-summary
    # parts are not the answer and are skipped.
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise ExternalServiceError(f"{provider} returned an empty answer",
                                   detail={"finish": candidate.get("finishReason")})
    if candidate.get("finishReason") == "MAX_TOKENS":
        # Truncated by OUR output cap. The caller's parse/repair path sees
        # incomplete output; say so in the log rather than let it look like a
        # model formatting error.
        logger.warning(f"{provider} output hit max_tokens; response is truncated",
                       extra={"max_tokens": max_tokens, "chars": len(text)})
    return text


@retry_llm
async def _call_gemini(api_key: str, prompt: str, *, system: str,
                       temperature: float, max_tokens: int) -> LLMResult:
    settings = get_settings()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    # The key travels in a HEADER, never the query string. It used to be
    # `params={"key": ...}`, which put it in the request URL — and httpx puts the
    # URL in every HTTPStatusError message, which tenacity's retry logger and
    # the router's failover warning both print. Every 503 from Gemini wrote a
    # live API key to the log stream (and from there to Cloud Logging).
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
    if resp.status_code == 429:
        raise RateLimitedError("gemini rate limited")
    resp.raise_for_status()
    data = resp.json()
    text = _gemini_answer_text(data, "gemini", max_tokens)
    usage = data.get("usageMetadata", {})
    t_in = usage.get("promptTokenCount", 0)
    t_out = usage.get("candidatesTokenCount", 0)
    LLM_TOKENS.labels("gemini", "in").inc(t_in)
    LLM_TOKENS.labels("gemini", "out").inc(t_out)
    return LLMResult(text, "gemini", t_in, t_out)


_vertex_creds = None


def _vertex_token_sync() -> str:
    """ADC access token, refreshed when near expiry. google-auth is synchronous
    (it does network I/O on refresh), so callers run this in a thread."""
    global _vertex_creds
    import google.auth
    import google.auth.transport.requests
    if _vertex_creds is None:
        _vertex_creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _vertex_creds.valid:
        _vertex_creds.refresh(google.auth.transport.requests.Request())
    return _vertex_creds.token


@retry_llm
async def _call_vertex(project: str, prompt: str, *, system: str,
                       temperature: float, max_tokens: int) -> LLMResult:
    """Gemini on Vertex AI. Same request/response schema as the AI Studio API,
    different endpoint and auth - so the parsing below mirrors _call_gemini."""
    import asyncio
    settings = get_settings()
    loc = settings.vertex_location
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{project}/locations/{loc}/publishers/google/"
           f"models/{settings.vertex_model}:generateContent")
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    token = await asyncio.to_thread(_vertex_token_sync)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=body,
                                 headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 429:
        raise RateLimitedError("vertex rate limited")
    resp.raise_for_status()
    data = resp.json()
    text = _gemini_answer_text(data, "vertex", max_tokens)
    usage = data.get("usageMetadata", {})
    t_in = usage.get("promptTokenCount", 0)
    t_out = usage.get("candidatesTokenCount", 0)
    LLM_TOKENS.labels("vertex", "in").inc(t_in)
    LLM_TOKENS.labels("vertex", "out").inc(t_out)
    return LLMResult(text, "vertex", t_in, t_out)


@retry_llm
async def _call_openai_compatible(spec: ProviderSpec, api_key: str, prompt: str, *,
                                  system: str, temperature: float,
                                  max_tokens: int) -> LLMResult:
    settings = get_settings()
    model = getattr(settings, spec.model_setting)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {api_key}"}
    if spec.name == "openrouter":
        headers["X-Title"] = "veriscope"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            spec.base_url, headers=headers,
            json={"model": model, "messages": messages,
                  "temperature": temperature, "max_tokens": max_tokens},
        )
    if resp.status_code == 429:
        raise RateLimitedError(f"{spec.name} rate limited")
    resp.raise_for_status()
    data = resp.json()
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ExternalServiceError(
            f"{spec.name} returned no choices",
            detail={"body": str(data)[:300]},
        ) from exc
    if not text:
        # A null/empty content (refusal, tool-call-only, filtered) is not an
        # answer; failing over beats handing "" to a JSON parser.
        raise ExternalServiceError(f"{spec.name} returned an empty answer",
                                   detail={"finish": choice.get("finish_reason")})
    if choice.get("finish_reason") == "length":
        logger.warning(f"{spec.name} output hit max_tokens; response is truncated",
                       extra={"max_tokens": max_tokens, "chars": len(text)})
    usage = data.get("usage") or {}
    t_in = usage.get("prompt_tokens", 0)
    t_out = usage.get("completion_tokens", 0)
    LLM_TOKENS.labels(spec.name, "in").inc(t_in)
    LLM_TOKENS.labels(spec.name, "out").inc(t_out)
    return LLMResult(text, spec.name, t_in, t_out)


async def call_provider(name: str, prompt: str, *, system: str = "",
                        temperature: float = 0.2, max_tokens: int = 4096,
                        key_index: int = 0) -> LLMResult:
    """One call on one LANE: a provider plus which of its keys to spend."""
    spec = PROVIDERS[name]
    keys = provider_keys(name)
    if not keys:
        raise ExternalServiceError(f"{name} API key not configured")
    api_key = keys[key_index % len(keys)]
    if name == "vertex":
        return await _call_vertex(api_key, prompt, system=system,
                                  temperature=temperature, max_tokens=max_tokens)
    if name == "gemini":
        return await _call_gemini(api_key, prompt, system=system,
                                  temperature=temperature, max_tokens=max_tokens)
    return await _call_openai_compatible(spec, api_key, prompt, system=system,
                                         temperature=temperature, max_tokens=max_tokens)
