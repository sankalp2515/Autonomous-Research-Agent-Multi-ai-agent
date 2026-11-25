"""Background worker: claims jobs from the Redis queue and executes them.
Run as: python -m app.worker

Delivery guarantees (see app/stores/redis_store.py, "Job queue"):

* A claimed job holds a LEASE that this process renews while it works. If the
  process dies, the lease lapses and the maintenance sweep of any surviving
  worker requeues the job - recovery no longer waits for a restart.
* Nothing is ever wiped. Boot recovery used to delete the whole queue and
  rebuild it from Run rows, silently dropping every queued email, import and
  reindex on each restart.
* Runs are reconciled against the database: a run at queued/running with no
  job and no live executor gets a job. A run whose job is dead-lettered is
  marked failed, so a run that crashes its worker cannot be re-enqueued
  forever by the reconciler.
* SIGTERM is graceful: stop claiming, give the current job a grace period, then
  hand it back to the queue WITHOUT counting an attempt. Pipeline runs resume
  from their last node checkpoint, so an interrupted run loses at most one node.

Health: when WORKER_HEALTH_PORT (or PORT, as Cloud Run sets it) is present, a
tiny HTTP server answers /livez (event loop alive), /readyz (loop ticked
recently and Redis reachable) and /metrics (Prometheus). The worker previously
had no metrics endpoint at all, so its liveness was only visible in logs.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import time

from app.agents.graph import execute_run
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.stores import redis_store, vector_store

logger = get_logger("worker")

_shutdown = asyncio.Event()

MONITOR_SWEEP_INTERVAL = 1800     # how often the worker checks for due monitors
MONITOR_STALE_SECONDS = 21600     # re-check a project's watches every ~6h
MAINTENANCE_INTERVAL = 60         # lease reaper + run reconciler cadence
RECONCILE_MIN_AGE_SECONDS = 120   # never race the API between commit and enqueue

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_last_tick = time.monotonic()


def _redact_payload(payload: dict) -> dict:
    """Job payloads are logged for traceability; email addresses are not."""
    out = {}
    for k, v in (payload or {}).items():
        if k in ("email", "entries"):
            out[k] = "<redacted>"
        else:
            out[k] = v if isinstance(v, (int, float, bool)) else str(v)[:80]
    return out


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
        from app.services.mailer import send_org_invite
        await asyncio.to_thread(
            send_org_invite, payload["email"], payload.get("org_name", "workspace"),
            payload.get("inviter", ""), payload.get("role", "member"))
    else:
        logger.error("unknown job kind", extra={"kind": kind})


async def monitor_sweep() -> None:
    """Standing-agent heartbeat: enqueue a monitor check for every project with
    an active watch not checked in the last interval."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.db.models import Watch
    from app.db.session import session_scope

    if not await redis_store.acquire_lock("monitor_sweep", ttl=MONITOR_SWEEP_INTERVAL // 2):
        return  # another worker swept this interval
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MONITOR_STALE_SECONDS)
    async with session_scope() as session:
        # One grouped query, not one query per project.
        rows = (await session.execute(
            select(Watch.project_id,
                   func.count(Watch.id).filter(Watch.last_checked.is_(None)),
                   func.min(Watch.last_checked))
            .where(Watch.active == True)  # noqa: E712
            .group_by(Watch.project_id)
        )).all()
    due = [pid for pid, never, oldest in rows
           if never or (oldest is not None and oldest < cutoff)]
    for pid in due:
        await redis_store.enqueue_job("run_monitor", {"project_id": pid})
    if due:
        logger.info("monitor sweep enqueued", extra={"projects": len(due)})


async def _fail_runs(run_ids: list[str], reason: str) -> None:
    if not run_ids:
        return
    from app.db.models import Run
    from app.db.session import session_scope
    async with session_scope() as session:
        for rid in run_ids:
            run = await session.get(Run, rid)
            if run and run.status in ("queued", "running"):
                run.status = "failed"
                run.error = reason
                logger.error("run failed permanently", extra={"run_id": rid})


async def maintenance() -> None:
    """Leader-gated: requeue jobs whose worker died, then make sure every
    non-terminal run has exactly one way forward.

    Runs at boot and then every MAINTENANCE_INTERVAL seconds, so a dead peer's
    work is recovered by the survivors instead of waiting for a restart."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.models import Run
    from app.db.session import session_scope

    if not await redis_store.acquire_lock("maintenance", ttl=MAINTENANCE_INTERVAL - 5):
        return

    _, dead = await redis_store.reap_expired_jobs()
    await _fail_runs(
        [(j.get("payload") or {}).get("run_id") for j in dead
         if j.get("kind") == "run_pipeline" and (j.get("payload") or {}).get("run_id")],
        "The run stopped its worker repeatedly and was abandoned after "
        f"{redis_store.MAX_JOB_ATTEMPTS} attempts. Resume it to try again.")

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECONCILE_MIN_AGE_SECONDS)
    async with session_scope() as session:
        runs = (await session.scalars(
            select(Run).where(Run.status.in_(["queued", "running"]),
                              Run.created_at < cutoff)
            .order_by(Run.created_at.asc()).limit(500)
        )).all()
        candidates = [r.id for r in runs]
    if not candidates:
        return
    has_job = await redis_store.queued_run_ids()
    revived = 0
    for rid in candidates:
        if rid in has_job or await redis_store.run_lock_held(rid):
            continue
        await redis_store.enqueue_job("run_pipeline", {"run_id": rid})
        revived += 1
    if revived:
        logger.warning("re-enqueued runs with no job and no executor",
                       extra={"count": revived})


async def _run_with_lease(job: dict) -> None:
    """Execute one job while renewing its lease; honour shutdown with a grace
    period, then hand the job back un-penalised."""
    settings = get_settings()

    async def _beat() -> None:
        while True:
            await asyncio.sleep(redis_store.JOB_LEASE_BEAT)
            if not await redis_store.renew_job_lease(job, WORKER_ID):
                logger.warning("could not renew job lease", extra={"job_id": job.get("id")})

    started = time.perf_counter()
    task = asyncio.create_task(handle_job(job))
    beat = asyncio.create_task(_beat())
    stop = asyncio.create_task(_shutdown.wait())
    try:
        done, _ = await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        if task not in done:
            # Shutting down mid-job: give it the grace window, then interrupt.
            try:
                await asyncio.wait_for(asyncio.shield(task),
                                       timeout=settings.worker_shutdown_grace_seconds)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                await redis_store.fail_job(job, count_attempt=False)
                logger.warning("job interrupted by shutdown; returned to the queue",
                               extra={"kind": job.get("kind"), "job_id": job.get("id")})
                return
        exc = task.exception()
        if exc is not None:
            raise exc
        await redis_store.complete_job(job)
        logger.info("job complete", extra={"kind": job.get("kind"),
                                           "seconds": round(time.perf_counter() - started, 1)})
    except Exception:
        logger.exception("job failed", extra={"kind": job.get("kind"),
                                              "seconds": round(time.perf_counter() - started, 1)})
        outcome = await redis_store.fail_job(job)
        if outcome == "dead" and job.get("kind") == "run_pipeline":
            await _fail_runs([(job.get("payload") or {}).get("run_id")],
                             f"The run failed {redis_store.MAX_JOB_ATTEMPTS} times "
                             "and was abandoned. Resume it to try again.")
    finally:
        beat.cancel()
        stop.cancel()


# ── health server ───────────────────────────────────────────────────────────

async def _health_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin-1")
        path = line.split(" ")[1] if " " in line else "/"
        # Drain headers.
        while (await asyncio.wait_for(reader.readline(), timeout=5)) not in (b"\r\n", b"\n", b""):
            pass
        status, body, ctype = 404, b"not found", "text/plain"
        if path.startswith("/livez"):
            status, body = 200, b"ok"
        elif path.startswith("/readyz"):
            stale = time.monotonic() - _last_tick
            ok = stale < 60
            try:
                await redis_store.get_redis().ping()
            except Exception:
                ok = False
            status, body = (200, b"ok") if ok else (503, b"not ready")
        elif path.startswith("/metrics"):
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
            status, body, ctype = 200, generate_latest(), CONTENT_TYPE_LATEST
        reason = {200: "OK", 404: "Not Found", 503: "Service Unavailable"}[status]
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\n"
                     f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                     .encode() + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def _start_health_server():
    port = os.environ.get("WORKER_HEALTH_PORT") or os.environ.get("PORT")
    if not port:
        return None
    server = await asyncio.start_server(_health_handler, "0.0.0.0", int(port))
    logger.info("worker health server listening", extra={"port": int(port)})
    return server


async def _update_queue_metrics() -> None:
    try:
        from app.core.observability import QUEUE_DEPTH
        QUEUE_DEPTH.labels("main").set(await redis_store.queue_depth())
        QUEUE_DEPTH.labels("dead").set(await redis_store.dead_letter_depth())
    except Exception:
        pass


async def main() -> None:
    global _last_tick
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    from app.core.prod_checks import enforce_production_settings
    enforce_production_settings(settings, process="worker")
    # The worker is where verification actually runs, so it must not start
    # able to ship quote-only claims.
    from app.verification.gate import assert_verification_ready
    assert_verification_ready()
    from app.llm.tracing import init_langsmith
    init_langsmith()
    from app.core.otel import init_otel
    init_otel(service_name="veriscope-worker")
    health = await _start_health_server()
    await init_db()
    await vector_store.ensure_ready()
    try:
        await maintenance()
    except Exception:
        logger.exception("boot maintenance failed; continuing")
    logger.info("worker started", extra={"worker_id": WORKER_ID})

    idle_polls = 0
    last_sweep = 0.0
    last_maintenance = time.time()
    while not _shutdown.is_set():
        _last_tick = time.monotonic()
        try:
            if time.time() - last_maintenance > MAINTENANCE_INTERVAL:
                last_maintenance = time.time()
                try:
                    await maintenance()
                except Exception:
                    logger.exception("maintenance failed")
                await _update_queue_metrics()
            job = await redis_store.claim_job(timeout=5, worker_id=WORKER_ID)
            if job is None:
                idle_polls += 1
                if idle_polls % 6 == 0:
                    depth = await redis_store.queue_depth()
                    logger.info("worker heartbeat",
                                extra={"queue_depth": depth, "idle_polls": idle_polls})
                if time.time() - last_sweep > MONITOR_SWEEP_INTERVAL:
                    last_sweep = time.time()
                    try:
                        await monitor_sweep()
                    except Exception:
                        logger.exception("monitor sweep failed")
                continue
            idle_polls = 0
            logger.info("job claimed", extra={"kind": job.get("kind"),
                                              "job_id": job.get("id"),
                                              "payload": _redact_payload(job.get("payload", {}))})
            await _run_with_lease(job)
        except Exception:
            # The loop must never die on a transient error (Redis blip, etc.).
            logger.exception("worker loop error; continuing")
            await asyncio.sleep(2.0)

    if health is not None:
        health.close()
    logger.info("worker stopped", extra={"worker_id": WORKER_ID})


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
