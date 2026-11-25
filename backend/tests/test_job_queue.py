"""The job queue: leased claims, a reaper for dead workers, nothing ever wiped.

Two shipped bugs this pins:
  * a crashed worker's job sat in PROCESSING until some worker RESTARTED;
  * boot recovery deleted the queue, dropping every queued email and import.
Runs against fakeredis with Lua, so the claim script itself is exercised.
"""

import json

import fakeredis
import pytest

from app.stores import redis_store as rs


@pytest.fixture
def redis(monkeypatch):
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(rs, "get_redis", lambda: r)
    return r


async def test_claim_moves_the_job_and_takes_a_lease(redis):
    jid = await rs.enqueue_job("reindex", {"project_id": "p"})
    job = await rs.claim_job(timeout=0, worker_id="w1")
    assert job["id"] == jid and job["kind"] == "reindex"
    assert await redis.llen(rs.QUEUE) == 0
    assert await redis.llen(rs.PROCESSING) == 1
    assert await redis.get(f"jobs:lease:{jid}") == "w1"
    assert 0 < await redis.ttl(f"jobs:lease:{jid}") <= rs.JOB_LEASE_TTL


async def test_complete_removes_job_and_lease(redis):
    await rs.enqueue_job("reindex", {"project_id": "p"})
    job = await rs.claim_job(timeout=0)
    await rs.complete_job(job)
    assert await redis.llen(rs.PROCESSING) == 0
    assert not await redis.exists(f"jobs:lease:{job['id']}")


async def test_reaper_requeues_a_dead_workers_job_and_leaves_live_ones(redis):
    await rs.enqueue_job("reindex", {"project_id": "dead"})
    await rs.enqueue_job("reindex", {"project_id": "alive"})
    dead = await rs.claim_job(timeout=0, worker_id="w-dead")
    alive = await rs.claim_job(timeout=0, worker_id="w-alive")
    await redis.delete(f"jobs:lease:{dead['id']}")  # its worker stopped renewing

    requeued, dead_lettered = await rs.reap_expired_jobs()
    assert requeued == 1 and dead_lettered == []
    queued = [json.loads(x) for x in await redis.lrange(rs.QUEUE, 0, -1)]
    assert [q["payload"]["project_id"] for q in queued] == ["dead"]
    assert queued[0]["attempts"] == 1
    still = [json.loads(x)["id"] for x in await redis.lrange(rs.PROCESSING, 0, -1)]
    assert still == [alive["id"]]


async def test_a_job_that_keeps_killing_its_worker_reaches_the_dead_letter_queue(redis):
    await rs.enqueue_job("run_pipeline", {"run_id": "r1"})
    dead = []
    for _ in range(rs.MAX_JOB_ATTEMPTS):
        job = await rs.claim_job(timeout=0)
        await redis.delete(f"jobs:lease:{job['id']}")
        _, d = await rs.reap_expired_jobs()
        dead.extend(d)
    assert await redis.llen(rs.DLQ) == 1
    assert [j["payload"]["run_id"] for j in dead] == ["r1"]


async def test_failures_count_attempts_but_shutdowns_do_not(redis):
    await rs.enqueue_job("reindex", {"project_id": "p"})
    job = await rs.claim_job(timeout=0)
    assert await rs.fail_job(job, count_attempt=False) == "requeued"
    job = await rs.claim_job(timeout=0)
    assert job["attempts"] == 0
    assert await rs.fail_job(job) == "requeued"
    job = await rs.claim_job(timeout=0)
    assert job["attempts"] == 1


async def test_fail_after_the_reaper_took_it_does_not_duplicate(redis):
    await rs.enqueue_job("reindex", {"project_id": "p"})
    job = await rs.claim_job(timeout=0)
    await redis.delete(f"jobs:lease:{job['id']}")
    await rs.reap_expired_jobs()
    assert await rs.fail_job(job) == "gone"
    assert await redis.llen(rs.QUEUE) == 1


async def test_legacy_entries_without_an_id_are_recovered_once(redis):
    legacy = json.dumps({"kind": "send_invite_email", "payload": {"email": "x"}, "attempts": 0})
    await redis.rpush(rs.PROCESSING, legacy)
    requeued, _ = await rs.reap_expired_jobs()
    assert requeued == 1
    (raw,) = await redis.lrange(rs.QUEUE, 0, -1)
    assert json.loads(raw)["id"]


async def test_nothing_in_the_queue_is_ever_deleted_by_recovery(redis, monkeypatch):
    """The old boot recovery DEL'd the queue. Maintenance must leave every
    non-run job exactly where it was."""
    import app.worker as worker

    await rs.enqueue_job("send_invite_email", {"email": "a@b.c"})
    await rs.enqueue_job("import_bibtex", {"project_id": "p", "entries": []})

    class _Empty:
        async def __aenter__(self):
            class S:
                async def scalars(self, *_a, **_k):
                    class R:
                        def all(self):
                            return []
                    return R()
            return S()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("app.db.session.session_scope", lambda: _Empty())
    await worker.maintenance()
    kinds = [json.loads(x)["kind"] for x in await redis.lrange(rs.QUEUE, 0, -1)]
    assert kinds == ["send_invite_email", "import_bibtex"]


async def test_queued_run_ids_sees_waiting_and_executing_runs(redis):
    await rs.enqueue_job("run_pipeline", {"run_id": "waiting"})
    await rs.enqueue_job("run_pipeline", {"run_id": "running"})
    await rs.claim_job(timeout=0)
    await rs.enqueue_job("reindex", {"project_id": "p"})
    assert await rs.queued_run_ids() == {"waiting", "running"}


def test_job_payload_logging_redacts_email():
    from app.worker import _redact_payload
    out = _redact_payload({"email": "someone@example.com", "org_name": "Lab", "role": "member"})
    assert out["email"] == "<redacted>" and "example.com" not in json.dumps(out)
