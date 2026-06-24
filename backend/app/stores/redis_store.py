"""Redis: ephemeral state only (custody rule - everything here must be
reconstructable from Postgres + Qdrant).

Provides: LLM response cache, provider token buckets, run progress
pub/sub-ish state for the UI, and a minimal reliable job queue with
retry + dead-letter semantics.
"""

import json
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("redis")

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _client


# ── LLM cache ────────────────────────────────────────────────────────────

async def cache_get(key: str) -> str | None:
    return await get_redis().get(f"llmcache:{key}")


async def cache_set(key: str, value: str, ttl: int) -> None:
    await get_redis().set(f"llmcache:{key}", value, ex=ttl)


# ── Token bucket throttle (free-tier RPM budgets) ───────────────────────

_BUCKET_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])      -- tokens per second
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or burst
local ts = tonumber(state[2]) or now
tokens = math.min(burst, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, 120)
return allowed
"""


async def acquire_token(provider: str, rpm: int) -> bool:
    """Try to take one request token for a provider. Non-blocking."""
    r = get_redis()
    allowed = await r.eval(
        _BUCKET_LUA, 1, f"bucket:{provider}", rpm / 60.0, max(rpm, 1), time.time()
    )
    return bool(allowed)


# ── Run progress (read by /api/status, written by the worker) ────────────

async def publish_progress(run_id: str, payload: dict[str, Any]) -> None:
    r = get_redis()
    payload = {**payload, "at": time.time()}
    await r.set(f"run:progress:{run_id}", json.dumps(payload), ex=3600)
    await r.rpush(f"run:events:{run_id}", json.dumps(payload))
    await r.expire(f"run:events:{run_id}", 3600)
    await r.ltrim(f"run:events:{run_id}", -200, -1)


async def read_progress(run_id: str) -> dict[str, Any] | None:
    raw = await get_redis().get(f"run:progress:{run_id}")
    return json.loads(raw) if raw else None


async def read_events(run_id: str) -> list[dict[str, Any]]:
    rows = await get_redis().lrange(f"run:events:{run_id}", 0, -1)
    return [json.loads(x) for x in rows]


# ── Job queue (simple, transparent, reliable enough for one worker pool) ─

QUEUE = "jobs:main"
PROCESSING = "jobs:processing"
DLQ = "jobs:dead"
MAX_JOB_ATTEMPTS = 3


async def enqueue_job(kind: str, payload: dict[str, Any]) -> None:
    job = json.dumps({"kind": kind, "payload": payload, "attempts": 0})
    await get_redis().rpush(QUEUE, job)


async def queue_depth() -> int:
    try:
        return int(await get_redis().llen(QUEUE))
    except Exception:
        return -1


async def claim_job(timeout: int = 5) -> dict[str, Any] | None:
    """Atomically move a job to the processing list so a crashed worker
    never loses it.

    Uses a non-blocking LMOVE poll instead of BLMOVE: the blocking variant
    holds the connection server-side for `timeout`s, which races the client
    socket read timeout and raises spurious TimeoutErrors on an idle queue.
    Polling sidesteps that entirely, and any transient Redis error returns
    None (no job) so an idle or briefly-unreachable queue never kills the
    worker loop."""
    import asyncio
    from redis import exceptions as redis_exc

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        try:
            raw = await get_redis().lmove(QUEUE, PROCESSING, "LEFT", "RIGHT")
        except (redis_exc.TimeoutError, redis_exc.ConnectionError) as exc:
            logger.warning("redis claim transient error", extra={"error": str(exc)[:120]})
            return None
        if raw:
            return json.loads(raw)
        if asyncio.get_event_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.5)


async def complete_job(job: dict[str, Any]) -> None:
    await get_redis().lrem(PROCESSING, 1, json.dumps(job))


async def fail_job(job: dict[str, Any]) -> None:
    r = get_redis()
    await r.lrem(PROCESSING, 1, json.dumps(job))
    job["attempts"] += 1
    if job["attempts"] >= MAX_JOB_ATTEMPTS:
        await r.rpush(DLQ, json.dumps(job))
        logger.error("job moved to dead-letter queue", extra={"kind": job["kind"]})
    else:
        await r.rpush(QUEUE, json.dumps(job))
