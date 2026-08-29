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


def provider_configured(name: str) -> bool:
    spec = PROVIDERS[name]
    return bool(getattr(get_settings(), spec.api_key_setting))


def provider_rpm(name: str) -> int:
    spec = PROVIDERS[name]
    return int(getattr(get_settings(), spec.rpm_setting))


@retry_llm
async def _call_gemini(prompt: str, *, system: str, temperature: float,
                       max_tokens: int) -> LLMResult:
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
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=body, params={"key": settings.gemini_api_key})
    if resp.status_code == 429:
        raise RateLimitedError("gemini rate limited")
    resp.raise_for_status()
    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise ExternalServiceError(
            "gemini returned no candidates",
            detail={"finish": str(data.get("candidates", [{}])[:1])[:300]},
        ) from exc
    usage = data.get("usageMetadata", {})
    t_in = usage.get("promptTokenCount", 0)
    t_out = usage.get("candidatesTokenCount", 0)
    LLM_TOKENS.labels("gemini", "in").inc(t_in)
    LLM_TOKENS.labels("gemini", "out").inc(t_out)
    return LLMResult(text, "gemini", t_in, t_out)


@retry_llm
async def _call_openai_compatible(spec: ProviderSpec, prompt: str, *, system: str,
                                  temperature: float, max_tokens: int) -> LLMResult:
    settings = get_settings()
    api_key = getattr(settings, spec.api_key_setting)
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
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ExternalServiceError(
            f"{spec.name} returned no choices",
            detail={"body": str(data)[:300]},
        ) from exc
    usage = data.get("usage") or {}
    t_in = usage.get("prompt_tokens", 0)
    t_out = usage.get("completion_tokens", 0)
    LLM_TOKENS.labels(spec.name, "in").inc(t_in)
    LLM_TOKENS.labels(spec.name, "out").inc(t_out)
    return LLMResult(text, spec.name, t_in, t_out)


async def call_provider(name: str, prompt: str, *, system: str = "",
                        temperature: float = 0.2, max_tokens: int = 4096) -> LLMResult:
    spec = PROVIDERS[name]
    if not getattr(get_settings(), spec.api_key_setting):
        raise ExternalServiceError(f"{name} API key not configured")
    if name == "gemini":
        return await _call_gemini(prompt, system=system, temperature=temperature,
                                  max_tokens=max_tokens)
    return await _call_openai_compatible(spec, prompt, system=system,
                                         temperature=temperature, max_tokens=max_tokens)
