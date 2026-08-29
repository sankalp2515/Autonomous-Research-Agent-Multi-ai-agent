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


# ── Per-caller rate limit (fixed window) ─────────────────────────────────
async def rate_limit_ok(key: str, limit: int, window_sec: int = 60) -> bool:
    """Return False when `key` has exceeded `limit` requests in the current
    window. Fail-OPEN: any Redis hiccup returns True so the limiter can never
    take the API down — it only ever sheds load it can positively confirm."""
    try:
        r = get_redis()
        bucket = f"rl:{key}:{int(time.time() // window_sec)}"
        n = await r.incr(bucket)
        if n == 1:
            await r.expire(bucket, window_sec)
        return n <= limit
    except Exception:
        return True


# ── Idempotency (collapse duplicate submits of a retryable operation) ────

async def idempotency_get(key: str) -> str | None:
    try:
        return await get_redis().get(f"idem:{key}")
    except Exception:
        return None  # fail open: a Redis blip must not block a legitimate submit


async def idempotency_set(key: str, value: str, ttl: int = 86_400) -> None:
    try:
        await get_redis().set(f"idem:{key}", value, ex=ttl, nx=True)
    except Exception:
        pass


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


# ── Per-run token accounting (durable cost/token tracking) ───────────────────
# Tokens are only Prometheus counters (process-global) — useless for a PER-PROJECT
# cost view. We accumulate per run in Redis during execution, then the pipeline
# persists the totals into runs.budgets_spent at the end (Postgres = durable).

async def incr_run_tokens(run_id: str, tokens_in: int, tokens_out: int) -> None:
    if not run_id or run_id == "-":
        return
    try:
        r = get_redis()
        k = f"runtokens:{run_id}"
        if tokens_in:
            await r.hincrby(k, "in", tokens_in)
        if tokens_out:
            await r.hincrby(k, "out", tokens_out)
        await r.expire(k, 86_400)
    except Exception:
        pass  # token accounting must never break a run


async def get_run_tokens(run_id: str) -> tuple[int, int]:
    try:
        d = await get_redis().hgetall(f"runtokens:{run_id}")
        return int(d.get("in", 0) or 0), int(d.get("out", 0) or 0)
    except Exception:
        return 0, 0


# ── Provider circuit breaker (skip a hard-down provider, don't pay its RTT) ───
# A provider that returns a HARD failure (402 unfunded, 401/403 bad key, or
# repeated connection errors) should be skipped for a cooldown instead of being
# retried on every call and adding a wasted round-trip to the fallback chain —
# the "trailing unfunded provider taxes every request" problem. Transient 429s
# are NOT circuit-worthy (that's throttling, handled by the token bucket).

async def circuit_open(provider: str) -> bool:
    try:
        return bool(await get_redis().get(f"circuit:{provider}"))
    except Exception:
        return False  # fail open: never let a Redis blip hide a usable provider


async def trip_circuit(provider: str, ttl: int = 300) -> None:
    try:
        await get_redis().set(f"circuit:{provider}", "1", ex=ttl)
    except Exception:
        pass


# ── Run progress (read by /api/status, written by the worker) ────────────

def _channel(run_id: str) -> str:
    return f"run:channel:{run_id}"


async def publish_progress(run_id: str, payload: dict[str, Any]) -> None:
    r = get_redis()
    payload = {**payload, "at": time.time()}
    blob = json.dumps(payload)
    # Snapshot (for reconnects / initial render) + append-only event log …
    await r.set(f"run:progress:{run_id}", blob, ex=3600)
    await r.rpush(f"run:events:{run_id}", blob)
    await r.expire(f"run:events:{run_id}", 3600)
    await r.ltrim(f"run:events:{run_id}", -200, -1)
    # … and a fan-out publish so SSE subscribers wake instantly instead of
    # polling every second (the snapshot key covers anyone who reconnects).
    await r.publish(_channel(run_id), blob)


async def read_progress(run_id: str) -> dict[str, Any] | None:
    raw = await get_redis().get(f"run:progress:{run_id}")
    return json.loads(raw) if raw else None


async def subscribe_progress(run_id: str):
    """Async generator yielding progress payloads pushed for a run. Pub/Sub
    replaces per-second polling; the caller still reads the snapshot first (to
    catch anything published before subscribing) and periodically re-reads it
    as a backstop for missed messages. Always closes the subscription."""
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(_channel(run_id))
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=10.0)
            if msg is None:
                yield None  # idle tick — lets the caller re-check terminal state
                continue
            data = msg.get("data")
            if data:
                try:
                    yield json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    continue
    finally:
        try:
            await pubsub.unsubscribe(_channel(run_id))
            await pubsub.aclose()
        except Exception:
            pass


# ── Distributed lock (single-leader startup work across N workers) ───────

async def acquire_lock(name: str, ttl: int = 60) -> bool:
    """Best-effort mutual exclusion via SET NX EX. Returns True to exactly one
    caller within the TTL window. Used to make startup orphan-recovery safe
    when more than one worker boots concurrently."""
    return bool(await get_redis().set(f"lock:{name}", "1", nx=True, ex=ttl))


# ── Per-run execution lock (prevents double-execution of one run) ────────────
# A run must be executed by AT MOST ONE worker at a time. Without this, a run
# actively executing on worker-A can be re-enqueued (by `/runs/{id}/resume` or by
# another worker's orphan recovery, which rebuilds the queue from non-terminal
# runs) and picked up by worker-B — producing duplicate claims/reports for the
# same run_id. The lock carries an owner token so only the holder can release it
# (a compare-and-delete), and a TTL so a crashed holder's lock self-heals and the
# run becomes recoverable.

_RUNLOCK_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


_RUNLOCK_REFRESH_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


async def acquire_run_lock(run_id: str, ttl: int) -> str | None:
    """Try to claim exclusive execution of `run_id`. Returns an owner token to
    pass to release_run_lock, or None if another worker already holds it."""
    import uuid
    token = uuid.uuid4().hex
    ok = await get_redis().set(f"runlock:{run_id}", token, nx=True, ex=ttl)
    return token if ok else None


async def refresh_run_lock(run_id: str, token: str, ttl: int) -> bool:
    """Extend OUR hold on a run lock. Returns False if we no longer own it.

    WHY A HEARTBEAT AND NOT A LONG TTL. The lock TTL was sized to cover a whole
    run (wall budget + 5 min). That is correct while a worker is alive and wrong
    the moment one dies: a restarted or crashed worker leaves the lock held for
    up to ~95 minutes, and every recovery attempt in that window logs "run
    already executing on another worker; skipping duplicate" and gives up. The
    run sits at status=running forever, which is exactly what a stale
    "How to reduce to hullcinations in RAG?" run was doing in this database.

    With a heartbeat the lock only has to outlive one beat, so a dead holder's
    lock expires in minutes and the run becomes recoverable — while a LIVE
    holder keeps renewing and duplicate execution is still impossible."""
    try:
        renewed = await get_redis().eval(
            _RUNLOCK_REFRESH_LUA, 1, f"runlock:{run_id}", token, str(ttl))
        return bool(renewed)
    except Exception:
        # A refresh we could not perform is not a reason to kill a running
        # pipeline; the worst case is the lock expiring and a duplicate being
        # admitted, which the run-status check in execute_run then rejects.
        return True


async def run_lock_held(run_id: str) -> bool:
    """Is a LIVE worker executing this run right now?

    The lock is heartbeat-renewed, so its presence is the only trustworthy
    answer: a run row can say `running` long after the worker that wrote it
    died. `/cancel` uses this to tell the two cases apart — a held run is
    stopped by its worker, an unheld one has nobody to stop it and must be
    marked terminal by the API or the Stop button does nothing forever.

    Fails SAFE (True): if Redis cannot be reached we assume a worker holds it
    rather than marking a live run terminal underneath itself."""
    try:
        return await get_redis().exists(f"runlock:{run_id}") == 1
    except Exception:
        return True


async def release_run_lock(run_id: str, token: str) -> None:
    """Release only if we still own the lock (compare-and-delete). Never raises —
    a lost lock (TTL expiry) just means someone else may recover the run."""
    try:
        await get_redis().eval(_RUNLOCK_RELEASE_LUA, 1, f"runlock:{run_id}", token)
    except Exception:
        pass


# ── Cancellation signal ─────────────────────────────────────────────────
#
# WHY REDIS AND NOT THE RUN ROW. The stopper is the API process; the thing that
# must notice is the WORKER, mid-node, inside a 20-minute extraction loop. A
# status column would only be read at the next checkpoint write, so the worker
# would keep spending LLM calls and wall clock on a run the user already
# abandoned — the exact cost the button exists to stop. A Redis flag is read in
# microseconds, so the pipeline can poll it between papers, not between nodes.
#
# The DB row remains the durable truth (status="cancelled" is written when the
# pipeline actually unwinds). This key is only the fast in-flight signal, and it
# carries a TTL so a flag set for a run that never gets claimed cannot poison a
# later resume of the same id.
_CANCEL_TTL = 6 * 3600


async def request_cancel(run_id: str) -> None:
    await get_redis().set(f"run:cancel:{run_id}", "1", ex=_CANCEL_TTL)


async def cancel_requested(run_id: str) -> bool:
    """Never raises: a Redis blip must not abort a healthy run. Failing closed
    here would mean 'unreachable Redis == stop the pipeline', which turns a
    cache outage into silent data loss."""
    try:
        return await get_redis().exists(f"run:cancel:{run_id}") == 1
    except Exception:
        return False


async def clear_cancel(run_id: str) -> None:
    """Consume the flag once the run has actually stopped, so a later resume of
    the same run id starts clean."""
    try:
        await get_redis().delete(f"run:cancel:{run_id}")
    except Exception:
        pass


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
