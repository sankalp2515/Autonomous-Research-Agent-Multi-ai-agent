"""A cached response that cannot be parsed is worse than no cache at all.

WHAT HAPPENED. `complete` writes the provider's text to the LLM cache the
moment it arrives - before anything checks that it parses. `complete_json`
validates afterwards. So a malformed response was stored under the prompt's
key and served for the full TTL, and every later call paid MORE than an
uncached one: a cache read, a failed parse, and a full repair chain on a
different provider. It could never heal, because nothing ever evicted it.

Observed live on `step=screen` during a run that was supposed to be warm:

    json repair attempt (step=screen provider=cache ...)
    llm call start      (provider=nvidia step=screen)
    provider failed     (nvidia 503)            <- 126 seconds
    llm call ok         (provider=groq  3090ms)
    slow request        /api/screen ms=129393

A "cached" screening call took 129 seconds and would have taken 129 seconds
every single time. The screening reasons the researcher then saw were partly
the hardcoded fallback, because only some candidates survived that chain.

The fix is two-sided: evict the poisoned entry, and write the output that
actually VALIDATED back under the original key so the repair is paid for once.
"""

import pytest

from app.agents.schemas import Clarification
from app.llm import router


class _Result:
    def __init__(self, text, provider):
        self.text = text
        self.provider = provider
        self.tokens_in = 0
        self.tokens_out = 0


GOOD = ('{"domain": "IR", "objective": "compare systems", '
        '"sub_questions": ["what is measured?"], "field": "computer science"}')


@pytest.fixture
def spy(monkeypatch):
    """Capture cache writes/deletes and script what `complete` returns."""
    box = {"deleted": [], "set": [], "calls": []}

    async def fake_delete(key):
        box["deleted"].append(key)

    async def fake_set(key, value, ttl):
        box["set"].append((key, value))

    monkeypatch.setattr(router.redis_store, "cache_delete", fake_delete)
    monkeypatch.setattr(router.redis_store, "cache_set", fake_set)
    return box


async def test_a_poisoned_cache_entry_is_evicted(spy, monkeypatch):
    """The entry that cannot parse must not survive to poison the next call."""
    async def fake_complete(step, prompt, **kw):
        spy["calls"].append(kw.get("use_cache", True))
        # First call: the cache hands back junk. Repair: a live provider.
        return (_Result("not json at all", "cache") if len(spy["calls"]) == 1
                else _Result(GOOD, "groq"))

    monkeypatch.setattr(router, "complete", fake_complete)
    out = await router.complete_json("clarify", "a prompt", Clarification)

    assert out.domain == "IR"
    assert len(spy["deleted"]) == 1, "the poisoned entry was left in place"


async def test_the_repaired_output_is_cached_under_the_original_key(spy, monkeypatch):
    """Otherwise the repair is re-paid on every future identical call - which
    is exactly the cost this whole caching layer exists to remove."""
    async def fake_complete(step, prompt, **kw):
        spy["calls"].append(kw.get("use_cache", True))
        return (_Result("not json at all", "cache") if len(spy["calls"]) == 1
                else _Result(GOOD, "groq"))

    monkeypatch.setattr(router, "complete", fake_complete)
    await router.complete_json("clarify", "a prompt", Clarification)

    assert spy["set"], "the repaired output was not cached"
    written_key, written_value = spy["set"][0]
    assert written_key == spy["deleted"][0], (
        "the repair was cached under a different key than the one that was "
        "evicted, so the next identical call still misses")
    assert written_value == GOOD


async def test_a_live_provider_failure_does_not_evict_anything(spy, monkeypatch):
    """Only a CACHED result is poison. A live provider returning junk is an
    ordinary repair, and there is no cache entry of ours to blame for it."""
    async def fake_complete(step, prompt, **kw):
        spy["calls"].append(kw.get("use_cache", True))
        return (_Result("not json", "gemini") if len(spy["calls"]) == 1
                else _Result(GOOD, "groq"))

    monkeypatch.setattr(router, "complete", fake_complete)
    await router.complete_json("clarify", "a prompt", Clarification)

    assert spy["deleted"] == []


async def test_a_clean_response_is_never_re_cached(spy, monkeypatch):
    """The happy path must not do extra work: `complete` already cached it."""
    async def fake_complete(step, prompt, **kw):
        spy["calls"].append(kw.get("use_cache", True))
        return _Result(GOOD, "cache")

    monkeypatch.setattr(router, "complete", fake_complete)
    out = await router.complete_json("clarify", "a prompt", Clarification)

    assert out.domain == "IR"
    assert spy["deleted"] == [] and spy["set"] == []
    assert len(spy["calls"]) == 1, "a parseable cache hit still called a provider"
