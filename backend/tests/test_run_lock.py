"""A dead worker must not hold a run hostage.

FOUND LIVE. This database contained a run stuck at status=running since the
previous day. Its worker had been restarted mid-run, and because the lock TTL
was sized to cover a whole run (wall budget + 5 minutes), the dead worker's
claim stayed valid for ~95 minutes — during which every recovery attempt logged
"run already executing on another worker; skipping duplicate" and gave up. The
exclusion that exists to prevent double execution had turned into a way to
prevent ANY execution.

The fix keeps exclusivity and drops the hostage window: a short TTL that a live
worker renews on a heartbeat. A live holder is still the only holder; a dead one
releases within one TTL.
"""

import app.agents.graph as graph
from app.stores import redis_store


def test_the_ttl_is_short_enough_to_recover_from_a_dead_worker():
    """The whole defect was a TTL measured in hours. It must now be minutes,
    and comfortably shorter than the wall budget it used to be derived from."""
    assert graph.RUN_LOCK_TTL <= 300
    from app.core.config import get_settings
    assert graph.RUN_LOCK_TTL < get_settings().run_max_wall_seconds


def test_the_heartbeat_beats_faster_than_the_lock_expires():
    """If a beat could arrive after expiry, a healthy worker would lose its own
    lock mid-run and a duplicate could be admitted."""
    assert graph.RUN_LOCK_BEAT < graph.RUN_LOCK_TTL
    # Enough slack for a slow beat (a blocked event loop, a Redis hiccup).
    assert graph.RUN_LOCK_BEAT <= graph.RUN_LOCK_TTL / 2


async def test_refresh_only_extends_a_lock_we_still_own(monkeypatch):
    calls = {}

    class _FakeRedis:
        async def eval(self, _lua, _n, key, token, ttl):
            calls.update(key=key, token=token, ttl=ttl)
            return 1 if token == "mine" else 0

    monkeypatch.setattr(redis_store, "get_redis", lambda: _FakeRedis())

    assert await redis_store.refresh_run_lock("r1", "mine", 180) is True
    assert calls["key"] == "runlock:r1" and calls["ttl"] == "180"
    assert await redis_store.refresh_run_lock("r1", "someone-else", 180) is False


async def test_a_refresh_failure_never_kills_a_running_pipeline(monkeypatch):
    """Redis being briefly unreachable is not a reason to abort a 40-minute run;
    the run-status check in execute_run is the real backstop against duplicates."""
    class _Broken:
        async def eval(self, *_a):
            raise RuntimeError("redis down")

    monkeypatch.setattr(redis_store, "get_redis", lambda: _Broken())
    assert await redis_store.refresh_run_lock("r1", "mine", 180) is True
