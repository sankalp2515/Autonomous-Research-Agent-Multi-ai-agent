"""Stopping a run is a first-class outcome, not a failure and not a no-op.

Before this existed there was no way to stop a run at all: a question launched
by mistake spent its full wall budget — on the observed hardware, ~35 minutes of
PDF downloads, embeddings and LLM calls — with the only recourse being to kill
the worker, which stranded the run at `status=running` forever.

Four properties are pinned here, because each one was a way to get this wrong:

1. **A stop lands mid-loop, not at the node boundary.** `research` and
   `extract_evidence` each iterate over every paper inside ONE node, so a check
   that only ran between nodes would leave the button doing nothing for up to
   twenty minutes.
2. **A stop is never swallowed.** Both loops use
   `asyncio.gather(..., return_exceptions=True)` so one bad paper cannot kill
   the batch — which also means a cancellation would be collected as a result
   and discarded unless it is explicitly re-raised.
3. **A stop is never relabelled as our failure.** `draft_sections` converts any
   exception into a `drafting_failed` gap. Letting `RunCancelled` reach that
   handler would publish "Veriscope failed while writing this section" about a
   run the user deliberately stopped — the same category error `gap_kind`
   exists to prevent.
4. **A stopped run is terminal but resumable**, and resuming it must consume the
   stop flag, or the resumed run aborts instantly at its first checkpoint.
"""

import asyncio
import time

import pytest

from app.agents import nodes
from app.core.exceptions import RunCancelled


def _state():
    return {"run_id": "r1", "project_id": "p", "query": "q",
            "llm_calls_used": 0, "started_at": time.time(), "coverage_notes": []}


@pytest.fixture
def cancelled(monkeypatch):
    """Flag this run as stopped."""
    async def yes(run_id):
        return run_id == "r1"
    monkeypatch.setattr(nodes.redis_store, "cancel_requested", yes)


@pytest.fixture
def not_cancelled(monkeypatch):
    async def no(_run_id):
        return False
    monkeypatch.setattr(nodes.redis_store, "cancel_requested", no)


@pytest.mark.asyncio
async def test_raises_when_the_run_is_flagged(cancelled):
    with pytest.raises(RunCancelled):
        await nodes.raise_if_cancelled(_state(), "ingest")


@pytest.mark.asyncio
async def test_is_a_no_op_for_a_healthy_run(not_cancelled):
    await nodes.raise_if_cancelled(_state(), "ingest")  # must not raise


@pytest.mark.asyncio
async def test_a_redis_outage_never_stops_a_healthy_run(monkeypatch):
    """Failing CLOSED here would turn a cache blip into silent data loss: every
    in-flight run would abort because we could not read a flag."""
    from app.stores import redis_store as real

    class _Dead:
        async def exists(self, *_a):
            raise ConnectionError("redis down")

    monkeypatch.setattr(real, "get_redis", lambda: _Dead())
    assert await real.cancel_requested("r1") is False


def test_gather_results_re_raise_a_cancellation():
    """A cancellation collected by `return_exceptions=True` must not be
    discarded alongside the per-paper failures the flag is there to tolerate."""
    settled = [{"doc_id": "a"}, ValueError("one bad paper"), RunCancelled("stopped")]
    with pytest.raises(RunCancelled):
        nodes.reraise_if_cancelled(settled)


def test_ordinary_failures_are_still_tolerated():
    nodes.reraise_if_cancelled([{"doc_id": "a"}, ValueError("one bad paper"), None])


@pytest.mark.asyncio
async def test_a_stop_is_not_reported_as_a_drafting_failure(monkeypatch):
    """The clearest way to get this wrong: `draft_sections` catches every
    exception and writes gap_kind="drafting_failed" — a statement that VERISCOPE
    broke. A user stop must unwind the run instead of libelling the system."""
    state = _state()
    state.update({"sections": [{"heading": "H", "sub_question": "H", "guidance": "",
                                "status": "pending", "claim_ids": [], "gap_note": "",
                                "regens_used": 0, "track": "academic"}],
                  "replan_targets": [], "replans_used": {}, "used_claim_texts": []})

    async def yes(_run_id):
        return True
    monkeypatch.setattr(nodes.redis_store, "cancel_requested", yes)

    async def noop(*_a, **_kw):
        return None
    monkeypatch.setattr(nodes, "_checkpoint", noop)
    monkeypatch.setattr(nodes, "publish_progress", noop)

    async def never_called(*_a, **_kw):
        raise AssertionError("drafting must not start on a cancelled run")
    monkeypatch.setattr(nodes, "_draft_one_section", never_called)

    with pytest.raises(RunCancelled):
        await nodes.draft_sections_node(state)

    assert state["sections"][0].get("gap_kind") != "drafting_failed"
    assert state["sections"][0]["status"] != "gap"


@pytest.mark.asyncio
async def test_the_flag_is_cleared_so_a_resume_is_not_re_cancelled(monkeypatch):
    """The flag has a TTL, not a lifetime. If a resume did not consume it, the
    resumed run would raise at its first checkpoint and the Resume button would
    look like it silently did nothing."""
    from app.stores import redis_store as real
    store: dict[str, str] = {}

    class _Fake:
        async def set(self, k, v, ex=None):
            store[k] = v
        async def exists(self, k):
            return 1 if k in store else 0
        async def delete(self, k):
            store.pop(k, None)

    monkeypatch.setattr(real, "get_redis", lambda: _Fake())
    await real.request_cancel("r1")
    assert await real.cancel_requested("r1") is True
    await real.clear_cancel("r1")
    assert await real.cancel_requested("r1") is False


# ── Preemption: the stop must land INSIDE the work, not after it ────────────
#
# The checkpoints above are cooperative, and the pipeline's hot loop is one
# `asyncio.gather` over every paper: all of its coroutines clear their check in
# the same millisecond and then sit on a semaphore for minutes. A stop pressed
# after that was invisible until the whole batch drained — the ~10-minute stop
# users actually experienced. `_invoke_pipeline` runs the graph under a watcher
# that CANCELS it, so the latency is one poll regardless of where it is stuck.

@pytest.mark.asyncio
async def test_a_stop_preempts_a_pipeline_that_never_reaches_a_checkpoint(monkeypatch):
    from app.agents import graph

    started = asyncio.Event()

    class _Hung:
        async def ainvoke(self, _state, _cfg):
            started.set()
            await asyncio.sleep(600)   # a download/LLM wave: no checkpoint in reach

    monkeypatch.setattr(graph, "get_pipeline", lambda: _Hung())
    monkeypatch.setattr(graph, "CANCEL_POLL_SECONDS", 0.01)

    async def yes(_run_id):
        return True
    monkeypatch.setattr(graph.redis_store, "cancel_requested", yes)

    t0 = time.perf_counter()
    with pytest.raises(RunCancelled):
        await asyncio.wait_for(graph._invoke_pipeline("r1", {}), timeout=5)
    assert started.is_set()
    assert time.perf_counter() - t0 < 2  # instant, not "after this stage finishes"


@pytest.mark.asyncio
async def test_a_worker_shutdown_is_not_a_user_stop(monkeypatch):
    """Cancellation has two sources. Only the flagged one is a cancelled RUN;
    a process shutdown must stay a CancelledError so the run is recovered and
    resumed rather than written off as terminal."""
    from app.agents import graph

    class _Hung:
        async def ainvoke(self, _state, _cfg):
            await asyncio.sleep(600)

    monkeypatch.setattr(graph, "get_pipeline", lambda: _Hung())
    monkeypatch.setattr(graph, "CANCEL_POLL_SECONDS", 0.01)

    async def no(_run_id):
        return False
    monkeypatch.setattr(graph.redis_store, "cancel_requested", no)

    task = asyncio.create_task(graph._invoke_pipeline("r1", {}))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_a_healthy_run_is_not_disturbed_by_the_watcher(monkeypatch):
    from app.agents import graph

    class _Fine:
        async def ainvoke(self, _state, _cfg):
            await asyncio.sleep(0.05)
            return {"ok": True}

    monkeypatch.setattr(graph, "get_pipeline", lambda: _Fine())
    monkeypatch.setattr(graph, "CANCEL_POLL_SECONDS", 0.01)

    async def no(_run_id):
        return False
    monkeypatch.setattr(graph.redis_store, "cancel_requested", no)
    await graph._invoke_pipeline("r1", {})   # must not raise


@pytest.mark.asyncio
async def test_an_unreachable_redis_reads_as_a_worker_still_holding_the_run(monkeypatch):
    """`/cancel` marks an unheld `running` row terminal itself. That verdict must
    fail SAFE: guessing 'no worker' during a Redis blip would mark a LIVE run
    cancelled underneath the worker still executing it."""
    from app.stores import redis_store as real

    class _Dead:
        async def exists(self, *_a):
            raise ConnectionError("redis down")

    monkeypatch.setattr(real, "get_redis", lambda: _Dead())
    assert await real.run_lock_held("r1") is True
