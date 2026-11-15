"""The routing contract: one chain, and every key is its own lane.

Two things are pinned here, and they are the whole change.

1. **One uniform order for every step: gemini -> openrouter -> groq.** The
   per-step chains this replaced assigned providers by task complexity, and the
   fleet drifted out from under that judgement — nvidia sat FIRST in six chains
   while returning 503s, so every heavy step paid a dead provider before
   reaching a live one, and deepseek answers 402 on the current key. Both are
   out of the rotation but still defined, so re-enabling is one line.

2. **Nine lanes, not three providers.** A free-tier key IS the rate limit, so
   4 gemini + 1 openrouter + 4 groq keys are throughput — but only if each key
   gets its own token bucket and its own circuit. Sharing one bucket would make
   four keys no faster than one; sharing one circuit would let a single revoked
   key sideline the three that still work.
"""

import httpx
import pytest

from app.core.config import Settings
from app.llm import clients, router


# ── The chain ───────────────────────────────────────────────────────────

def test_every_step_uses_the_same_order():
    expected = ["gemini", "openrouter", "groq"]
    for step, chain in router.ROUTING.items():
        assert chain == expected, f"step {step!r} diverged from the chain"
    assert router._DEFAULT_CHAIN == expected


def test_gemini_leads_and_groq_is_the_last_resort():
    """The two ends carry the intent: the provider being scaled with keys goes
    first, the fallback that must still answer when the others are throttled
    goes last."""
    for chain in router.ROUTING.values():
        assert chain[0] == "gemini"
        assert chain[-1] == "groq"


def test_failing_providers_are_out_of_the_rotation_but_not_deleted():
    for chain in router.ROUTING.values():
        assert "nvidia" not in chain
        assert "deepseek" not in chain
    assert "nvidia" in clients.PROVIDERS      # re-enabling stays a one-liner
    assert "deepseek" in clients.PROVIDERS


# ── Keys become lanes ───────────────────────────────────────────────────

def _fleet(monkeypatch, **kw) -> Settings:
    settings = Settings(_env_file=None, **kw)
    monkeypatch.setattr(clients, "get_settings", lambda: settings)
    return settings


def test_the_configured_fleet_is_four_one_four(monkeypatch):
    """The exact shape asked for — and the reason the config fields must exist:
    with `extra="ignore"`, GEMINI_API_KEY_2..4 in .env without a matching field
    are silently discarded, which is what made four keys behave as one."""
    _fleet(monkeypatch,
           gemini_api_key="g1", gemini_api_key_2="g2",
           gemini_api_key_3="g3", gemini_api_key_4="g4",
           openrouter_api_key="o1",
           groq_api_key="k1", groq_api_key_2="k2",
           groq_api_key_3="k3", groq_api_key_4="k4")
    assert clients.provider_keys("gemini") == ["g1", "g2", "g3", "g4"]
    assert clients.provider_keys("openrouter") == ["o1"]
    assert clients.provider_keys("groq") == ["k1", "k2", "k3", "k4"]


def test_duplicate_keys_collapse_into_one_lane(monkeypatch):
    """Two lanes sharing one real key would each be handed a full bucket and
    together overrun the provider's actual limit — a 429 storm built out of a
    copy-paste."""
    _fleet(monkeypatch, gemini_api_key="same", gemini_api_key_2="same",
           gemini_api_key_3="other")
    assert clients.provider_keys("gemini") == ["same", "other"]


def test_an_unconfigured_provider_has_no_lanes(monkeypatch):
    _fleet(monkeypatch, gemini_api_key="")
    assert clients.provider_keys("gemini") == []
    assert clients.provider_configured("gemini") is False


def test_lane_zero_keeps_the_bare_provider_name():
    """So existing Redis buckets and circuits — and the dashboard's per-provider
    view — keep meaning exactly what they meant before."""
    assert router._lane("gemini", 0) == "gemini"
    assert router._lane("gemini", 3) == "gemini#3"


def test_each_key_becomes_its_own_lane(monkeypatch):
    monkeypatch.setattr(router, "provider_keys",
                        lambda n: ["a", "b", "c", "d"] if n == "gemini" else ["x"])
    router._cursor.clear()
    lanes = router._lanes_for("gemini")
    assert len(lanes) == 4
    assert {router._lane(p, i) for p, i in lanes} == {
        "gemini", "gemini#1", "gemini#2", "gemini#3"}


def test_a_single_key_provider_has_exactly_one_lane(monkeypatch):
    monkeypatch.setattr(router, "provider_keys", lambda _n: ["o1"])
    assert router._lanes_for("openrouter") == [("openrouter", 0)]


def test_lanes_rotate_so_one_key_is_not_always_first(monkeypatch):
    """Without rotation every concurrent call starts at key 0, all fail to
    acquire its token, and they cascade down the same order together."""
    monkeypatch.setattr(router, "provider_keys", lambda _n: ["a", "b", "c", "d"])
    router._cursor.clear()
    firsts = {router._lanes_for("gemini")[0][1] for _ in range(4)}
    assert firsts == {0, 1, 2, 3}


def test_call_provider_selects_the_key_by_index(monkeypatch):
    """The lane index has to reach the wire, or every lane spends key 0."""
    _fleet(monkeypatch, groq_api_key="k1", groq_api_key_2="k2",
           groq_model="m", groq_rpm=25)
    sent = {}

    class _Client:
        def __init__(self, **_kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): return False

        async def post(self, url, **kwargs):
            sent["auth"] = (kwargs.get("headers") or {}).get("Authorization")
            request = httpx.Request("POST", url)
            return httpx.Response(
                200, request=request,
                json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(clients.httpx, "AsyncClient", _Client)

    import asyncio
    asyncio.run(clients.call_provider("groq", "hi", key_index=1))
    assert sent["auth"] == "Bearer k2"


@pytest.mark.asyncio
async def test_a_dead_key_cools_only_its_own_lane(monkeypatch):
    """401 is a fact about ONE credential. Cooling all four gemini keys because
    one was revoked would throw away three working ones."""
    from app.stores import redis_store

    class _Redis:
        def __init__(self):
            self.circuits = {}
        async def eval(self, *_a):
            return 1
        async def get(self, k):
            return self.circuits.get(k)
        async def set(self, k, v, ex=None):
            self.circuits[k] = v
        async def delete(self, k):
            self.circuits.pop(k, None)

    fake = _Redis()
    monkeypatch.setattr(redis_store, "get_redis", lambda: fake)

    async def miss(_k):
        return None
    monkeypatch.setattr(redis_store, "cache_get", miss)

    async def noop(*_a, **_kw):
        return None
    monkeypatch.setattr(redis_store, "cache_set", noop)

    monkeypatch.setattr(router, "provider_keys",
                        lambda n: ["g1", "g2"] if n == "gemini" else [])
    monkeypatch.setattr(router, "provider_configured", lambda n: n == "gemini")
    monkeypatch.setattr(router, "provider_rpm", lambda _n: 60)
    router._cursor.clear()

    async def call(_provider, _prompt, key_index=0, **_kw):
        if key_index == 0:
            request = httpx.Request("POST", "https://example.test")
            raise httpx.HTTPStatusError(
                "401", request=request,
                response=httpx.Response(401, request=request))
        return clients.LLMResult("ok", "gemini")
    monkeypatch.setattr(router, "call_provider", call)

    result = await router.complete("draft", "write", use_cache=False)
    assert result.provider == "gemini"
    assert fake.circuits.get("circuit:gemini") == "1"       # lane 0 only
    assert "circuit:gemini#1" not in fake.circuits
