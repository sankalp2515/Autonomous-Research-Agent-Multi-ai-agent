"""Background worker: claims jobs from the Redis queue and executes
pipeline runs. Run as: python -m app.worker

Crash-safe: jobs move to a processing list while running; failures retry
up to MAX_JOB_ATTEMPTS then land in the dead-letter queue with full logs.
"""

import asyncio
import os
import signal
import time

from app.agents.graph import execute_run
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.stores import redis_store
from app.stores.qdrant_store import ensure_collection

logger = get_logger("worker")

_shutdown = asyncio.Event()

MONITOR_SWEEP_INTERVAL = 1800     # how often the worker checks for due monitors
MONITOR_STALE_SECONDS = 21600     # re-check a project's watches every ~6h


async def handle_job(job: dict) -> None:
    kind = job.get("kind")
    payload = job.get("payload", {})
    if kind == "run_pipeline":
        await execute_run(payload["run_id"], scope=payload.get("scope", "all"),
                          since_year=payload.get("since_year", 0),
                          until_year=payload.get("until_year", 0),
                          min_citations=payload.get("min_citations", 0),
                          selected_papers=payload.get("selected_papers") or [])
    elif kind == "import_bibtex":
        from app.services.import_lib import import_bibtex_entries
        await import_bibtex_entries(payload["project_id"], payload["entries"])
    elif kind == "reindex":
        from app.db.session import session_scope
        from app.ingestion.pipeline import reindex_pending
        async with session_scope() as session:
            repaired = await reindex_pending(session, payload["project_id"])
        logger.info("reindex complete", extra={"chunks": repaired})
    elif kind == "run_monitor":
        from app.services.monitor import run_monitor
        found = await run_monitor(payload["project_id"])
        logger.info("monitor job complete", extra={"new_alerts": found})
    elif kind == "send_invite_email":
        # Durable delivery: queued so a shutdown between HTTP response and send
        # never loses the email, and the queue's retry/dead-letter applies.
        import asyncio as _asyncio

        from app.services.mailer import send_org_invite
        await _asyncio.to_thread(
            send_org_invite, payload["email"], payload.get("org_name", "workspace"),
            payload.get("inviter", ""), payload.get("role", "member"))
    else:
        logger.error("unknown job kind", extra={"kind": kind})


async def monitor_sweep() -> None:
    """Standing-agent heartbeat: enqueue a monitor check for every project with
    an active watch not checked in the last interval. This is what makes the
    agent 'standing' - it keeps looking without the user asking."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.models import Watch
    from app.db.session import session_scope

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MONITOR_STALE_SECONDS)
    async with session_scope() as session:
        rows = (await session.scalars(
            select(Watch.project_id).where(Watch.active == True).distinct()  # noqa: E712
        )).all()
        due = []
        for pid in rows:
            w = await session.scalar(
                select(Watch).where(Watch.project_id == pid, Watch.active == True)  # noqa: E712
                .order_by(Watch.last_checked.is_(None).desc(), Watch.last_checked.asc())
            )
            if w and (w.last_checked is None or w.last_checked < cutoff):
                due.append(pid)
    for pid in due:
        await redis_store.enqueue_job("run_monitor", {"project_id": pid})
    if due:
        logger.info("monitor sweep enqueued", extra={"projects": len(due)})


async def recover_orphans() -> None:
    """Self-heal on startup. Run rows are the source of truth: any run not in
    a terminal state has no live job after a crash/restart, so rebuild the
    queue from them. Prevents the 'stuck at running forever' orphans that a
    dead worker leaves behind.

    Leader-gated: the queue wipe + rebuild must run on EXACTLY ONE worker.
    Without the lock, a second worker booting concurrently would delete the
    queue (and any jobs a peer just enqueued) — silent data loss. Whoever wins
    the lock recovers; the rest skip and go straight to consuming."""
    from sqlalchemy import select

    from app.db.models import Run
    from app.db.session import session_scope

    if not await redis_store.acquire_lock("recover_orphans", ttl=60):
        logger.info("orphan recovery skipped (another worker holds the leader lock)")
        return

    redis = redis_store.get_redis()
    await redis.delete(redis_store.QUEUE, redis_store.PROCESSING)
    async with session_scope() as session:
        runs = (await session.scalars(
            select(Run).where(Run.status.in_(["queued", "running"]))
            .order_by(Run.created_at.asc())
        )).all()
    for run in runs:
        await redis_store.enqueue_job("run_pipeline", {"run_id": run.id})
    if runs:
        logger.info("recovered orphan runs", extra={"count": len(runs)})


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    # Fail fast at boot if this environment requires the NLI truth layer but has
    # it off — the worker is where verification actually runs, so it must not
    # start able to ship quote-only claims. (The gate raises regardless; this
    # turns a per-run failure into an immediate, obvious boot refusal.)
    from app.verification.gate import assert_verification_ready
    assert_verification_ready()
    # LangSmith: wire LANGCHAIN_* env so the LangGraph pipeline auto-traces the
    # worker's runs (this is where execute_run actually runs the graph).
    from app.llm.tracing import init_langsmith
    init_langsmith()
    from app.core.otel import init_otel
    init_otel(service_name="veriscope-worker")  # httpx/redis + manual node spans
    await init_db()
    await ensure_collection()
    await recover_orphans()
    logger.info("worker started", extra={"pid": os.getpid()})

    idle_polls = 0
    last_sweep = 0.0
    while not _shutdown.is_set():
        try:
            job = await redis_store.claim_job(timeout=5)
            if job is None:
                # Heartbeat (~every 30s): proves the worker is alive and shows
                # how many jobs are waiting. If these stop appearing in the
                # logs, the worker process died - the single clearest signal.
                idle_polls += 1
                if idle_polls % 6 == 0:
                    depth = await redis_store.queue_depth()
                    logger.info("worker heartbeat",
                                extra={"queue_depth": depth, "idle_polls": idle_polls})
                # Standing monitor sweep on the idle path.
                if time.time() - last_sweep > MONITOR_SWEEP_INTERVAL:
                    last_sweep = time.time()
                    try:
                        await monitor_sweep()
                    except Exception:
                        logger.exception("monitor sweep failed")
                continue
            idle_polls = 0
            started = time.perf_counter()
            logger.info("job claimed", extra={"kind": job.get("kind"),
                                              "payload": str(job.get("payload"))[:120]})
            try:
                await handle_job(job)
                await redis_store.complete_job(job)
                logger.info("job complete", extra={"kind": job.get("kind"),
                                                   "seconds": round(time.perf_counter() - started, 1)})
            except Exception:
                logger.exception("job failed", extra={"kind": job.get("kind"),
                                                      "seconds": round(time.perf_counter() - started, 1)})
                await redis_store.fail_job(job)
        except Exception:
            # Last-resort guard: the worker loop must never die on a transient
            # error (Redis blip, etc.). Log, pause briefly, keep polling.
            logger.exception("worker loop error; continuing")
            await asyncio.sleep(2.0)

    logger.info("worker stopped")


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is not None:
                try:
                    loop.add_signal_handler(sig, _shutdown.set)
                except NotImplementedError:
                    pass  # Windows: Ctrl+C raises KeyboardInterrupt instead
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
