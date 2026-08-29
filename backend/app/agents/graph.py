"""LangGraph topology v2.

The v1 fix is visible right here in the edges: draft_sections has a
conditional edge BACK to plan (bounded by per-sub-question replan budgets
inside the nodes), and assemble only ships gate-verified claims.
"""

import asyncio
import time

from langgraph.graph import END, StateGraph

from app.agents import nodes
from app.agents.state import PipelineState, new_state
from app.core.exceptions import RunCancelled
from app.core.logging import get_logger, run_id_var
from app.db.models import Run
from app.db.session import session_scope
from app.stores import redis_store
from app.stores.redis_store import publish_progress

logger = get_logger("graph")

# How long a claim survives without a heartbeat, and how often a live worker
# renews it. The gap between them absorbs a slow beat without dropping the lock.
RUN_LOCK_TTL = 180
RUN_LOCK_BEAT = 60


def build_pipeline():
    graph = StateGraph(PipelineState)
    graph.add_node("clarify", nodes.clarify_node)
    graph.add_node("plan", nodes.plan_node)
    graph.add_node("evidence_schema", nodes.evidence_schema_node)
    graph.add_node("research", nodes.research_node)
    graph.add_node("extract_evidence", nodes.extract_evidence_node)
    graph.add_node("report_architect", nodes.report_architect_node)
    graph.add_node("draft_sections", nodes.draft_sections_node)
    graph.add_node("assemble", nodes.assemble_node)
    graph.add_node("build_graph", nodes.build_graph_node)

    graph.set_entry_point("clarify")
    graph.add_conditional_edges(
        "clarify", nodes.clarify_route, {"plan": "plan", "end": END},
    )
    # P0-A: what evidence THIS question requires is declared BEFORE any
    # paper is read, so per-paper retrieval can aim at each required axis
    # instead of firing one generic objective query at every paper. The
    # node is idempotent, so the replan loop does not re-derive it.
    graph.add_edge("plan", "evidence_schema")
    graph.add_edge("evidence_schema", "research")
    # Phase 1: papers are read into a structured evidence matrix BEFORE any
    # outline exists, so downstream stages see the corpus as a body of evidence
    # rather than as chunks that happened to rank for a sub-question.
    # A run whose screen admitted NO papers stops here. Retrieval is scoped to
    # the project, not the run, so continuing would draft a report from papers
    # gathered for an earlier question — individually grounded sentences under a
    # funnel describing a corpus that was never used. Refusal is the honest
    # outcome (G4), so `research` gets the same escape hatch as `clarify`.
    graph.add_conditional_edges(
        "research", nodes.research_route,
        {"extract_evidence": "extract_evidence", "end": END},
    )
    graph.add_edge("extract_evidence", "report_architect")
    graph.add_edge("report_architect", "draft_sections")
    graph.add_conditional_edges(
        "draft_sections", nodes.should_replan,
        {"plan": "plan", "assemble": "assemble"},
    )
    graph.add_edge("assemble", "build_graph")
    graph.add_edge("build_graph", END)
    return graph.compile()


_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_pipeline()
    return _pipeline


# How often the worker asks Redis whether the user pressed Stop. This is the
# WORST-CASE latency of the stop button, so it is deliberately about a second:
# an EXISTS on one key is microseconds, and a run costs dollars a minute.
CANCEL_POLL_SECONDS = 1.0


async def _cancel_watch(run_id: str, target: asyncio.Task) -> None:
    """Poll the stop flag and CANCEL the pipeline task when it is raised.

    WHY PREEMPTION AND NOT ONLY CHECKPOINTS. `raise_if_cancelled` is a
    cooperative check: it only lands when control reaches it. That is fine for
    a sequential loop and useless for the shape the pipeline actually has —
    `research` builds ONE gather over every paper, so all ~40 coroutines pass
    their pre-download check within the same millisecond and then sit on a
    semaphore. A stop pressed a second later was not seen again until every
    download, parse and embed had finished: the observed ~10-minute stop.
    Waves of LLM calls (extraction, drafting) have the same problem one level
    down — a wave in flight is a provider timeout x retries of unstoppable work.

    Cancelling the task interrupts the awaits themselves, so the stop lands
    inside the in-flight HTTP call rather than after it. The checkpoints stay:
    they are the graceful path and they keep the unwind cheap. This is the
    backstop that makes the button mean the same thing everywhere.
    """
    try:
        while not target.done():
            await asyncio.sleep(CANCEL_POLL_SECONDS)
            if await redis_store.cancel_requested(run_id):
                logger.info("stop requested; preempting pipeline",
                            extra={"run_id": run_id})
                target.cancel()
                return
    except asyncio.CancelledError:
        return


async def _invoke_pipeline(run_id: str, state: PipelineState) -> None:
    """Run the graph under a stop watcher, translating a preemption into the
    same RunCancelled the cooperative checkpoints raise — so there is exactly
    one stop path downstream, terminal and not a failure."""
    task = asyncio.create_task(get_pipeline().ainvoke(state, {"recursion_limit": 40}))
    watcher = asyncio.create_task(_cancel_watch(run_id, task))
    try:
        await task
    except asyncio.CancelledError:
        # Ours (the user pressed Stop) or the worker's (process shutdown). Only
        # the first is a cancelled RUN; the second must stay a CancelledError so
        # the run remains recoverable rather than being marked terminal.
        if await redis_store.cancel_requested(run_id):
            raise RunCancelled("run stopped by the user") from None
        raise
    finally:
        watcher.cancel()


async def execute_run(run_id: str, scope: str = "all", since_year: int = 0,
                      until_year: int = 0, min_citations: int = 0,
                      selected_papers: list | None = None) -> None:
    """Entry point called by the worker. Resumes from checkpoint if the
    run was interrupted; recursion_limit bounds total graph steps as the
    last-resort loop guard above the in-state budgets.

    `scope` ("all" | "papers") selects which evidence classes to search; it
    only applies to a fresh run — a resumed run already carries its scope in
    the checkpointed state.

    Exclusive: a per-run Redis lock guarantees at most one worker executes a
    given run_id at a time, so a re-enqueued duplicate (resume, or another
    worker's orphan recovery) is skipped rather than run twice."""
    run_id_var.set(run_id)

    # SHORT lock + heartbeat, not a run-length TTL. A run-length TTL means a
    # worker that dies mid-run keeps the lock for ~95 minutes, during which every
    # recovery attempt logs "already executing on another worker" and the run is
    # stuck at status=running with nobody driving it (observed in this database).
    # A live worker renews every RUN_LOCK_BEAT seconds; a dead one stops renewing
    # and the run is recoverable within one TTL.
    lock_ttl = RUN_LOCK_TTL
    lock_token = await redis_store.acquire_run_lock(run_id, ttl=lock_ttl)
    if lock_token is None:
        logger.warning("run already executing on another worker; skipping duplicate",
                       extra={"run_id": run_id})
        return

    async def _heartbeat() -> None:
        """Keep our claim alive while the pipeline runs."""
        while True:
            await asyncio.sleep(RUN_LOCK_BEAT)
            if not await redis_store.refresh_run_lock(run_id, lock_token, RUN_LOCK_TTL):
                logger.warning("lost the run lock while still executing",
                               extra={"run_id": run_id})
                return

    beat = asyncio.create_task(_heartbeat())
    try:
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            if run is None:
                logger.error("run not found", extra={"run_id": run_id})
                return
            if run.status in ("completed", "completed_with_gaps", "done", "cancelled"):
                # Already finished (e.g. a stale re-enqueue after completion).
                logger.info("run already terminal; skipping", extra={"run_id": run_id})
                return
            if run.checkpoint:
                state: PipelineState = run.checkpoint  # resume
                # REBASE THE CLOCK. `started_at` is checkpointed, so a resumed
                # run used to measure its wall budget from ORIGINAL SUBMISSION —
                # including however long the worker was down. A restart an hour
                # into a run therefore came back with its entire time budget
                # already spent: observed live as a run that ingested 26 papers,
                # then skipped extraction in 0.11s after 11 of 200 LLM calls,
                # and reported the missing papers as an evidence gap.
                #
                # The budget is meant to bound WORK, not calendar time, so it is
                # rebased onto the work actually recorded in node_seconds. A
                # resume then continues with the remaining budget it earned,
                # and an interrupted run is no longer quietly destroyed.
                spent = sum((state.get("node_seconds") or {}).values())
                state["started_at"] = time.time() - spent
                logger.info("resuming run from checkpoint",
                            extra={"node": run.current_node,
                                   "work_seconds_so_far": round(spent)})
            else:
                state = new_state(run_id, run.project_id, run.query, scope=scope,
                                  since_year=since_year, until_year=until_year,
                                  min_citations=min_citations,
                                  selected_papers=selected_papers or [])
            run.status = "running"

        try:
            await _invoke_pipeline(run_id, state)
        except RunCancelled as exc:
            # A STOP IS A TERMINAL STATE, NOT A FAILURE. `failed` is offered a
            # Resume button and is counted as a Veriscope defect; a run the user
            # deliberately stopped is neither. The work already checkpointed
            # stays on the row, so the partial corpus is kept and the run can
            # still be resumed deliberately from where it was stopped.
            logger.info("run cancelled by user", extra={"run_id": run_id})
            stopped_at = "cancelled"
            async with session_scope() as session:
                run = await session.get(Run, run_id)
                if run:
                    # Read the node INSIDE the session: outside it the instance
                    # is detached and touching an unloaded attribute raises.
                    stopped_at = run.current_node or "cancelled"
                    run.status = "cancelled"
                    run.error = ""
            await publish_progress(run_id, {"node": stopped_at,
                                            "status": "cancelled", "kind": "refuse",
                                            "message": str(exc)})
            # Consume the flag: without this, a later deliberate resume of this
            # same run id would read a stale stop and abort immediately.
            await redis_store.clear_cancel(run_id)
            return
        except Exception as exc:
            logger.exception("run failed", extra={"run_id": run_id})
            async with session_scope() as session:
                run = await session.get(Run, run_id)
                if run:
                    run.status = "failed"
                    run.error = str(exc)[:1000]
            await publish_progress(run_id, {"node": "failed", "status": "failed",
                                            "kind": "error",
                                            "message": str(exc)[:300],
                                            "error": str(exc)[:300]})
            raise
    finally:
        beat.cancel()
        await redis_store.release_run_lock(run_id, lock_token)
