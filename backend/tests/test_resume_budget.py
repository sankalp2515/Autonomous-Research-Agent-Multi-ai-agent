"""A resumed run must keep the budget it earned, not the calendar.

`started_at` is part of the checkpoint, so a resumed run used to measure its
wall-clock budget from ORIGINAL SUBMISSION — including the time the worker was
down. Observed live: a run ingested 26 papers, was interrupted by a worker
restart, resumed, and then skipped extraction entirely in 0.11 seconds after
11 of its 200 LLM calls, reporting the unread papers as an evidence gap.

The budget bounds WORK, not elapsed calendar time. On resume the clock is
rebased onto the work actually recorded in `node_seconds`.
"""

import time

from app.agents.state import budget_left, budget_reason


def _rebase(state: dict) -> dict:
    """The rebase `execute_run` performs when it loads a checkpoint."""
    spent = sum((state.get("node_seconds") or {}).values())
    state["started_at"] = time.time() - spent
    return state


def test_downtime_does_not_consume_the_time_budget():
    """Submitted two hours ago, 10 minutes of actual work, worker was down for
    the rest. The run must resume with budget remaining."""
    two_hours_ago = time.time() - 7200
    state = {
        "started_at": two_hours_ago,
        "llm_calls_used": 11,
        "node_seconds": {"research": 589.0, "evidence_schema": 33.7},
    }
    # Before rebasing, the run looks exhausted purely because of the outage.
    assert not budget_left(state, max_calls=200, max_seconds=5400)

    _rebase(state)
    assert budget_left(state, max_calls=200, max_seconds=5400)


def test_work_that_genuinely_exceeds_the_budget_still_stops():
    """Rebasing must not become a way to run forever: real recorded work still
    counts against the budget across resumes."""
    state = {
        "started_at": time.time() - 60,
        "llm_calls_used": 20,
        "node_seconds": {"research": 3000.0, "extract_evidence": 2600.0},
    }
    _rebase(state)
    assert not budget_left(state, max_calls=200, max_seconds=5400)
    assert "time budget" in budget_reason(state, 200, 5400)


def test_the_call_budget_is_untouched_by_rebasing():
    state = {
        "started_at": time.time() - 10_000,
        "llm_calls_used": 200,
        "node_seconds": {"research": 10.0},
    }
    _rebase(state)
    assert not budget_left(state, max_calls=200, max_seconds=5400)
    assert "model-call budget" in budget_reason(state, 200, 5400)


def test_a_fresh_run_with_no_recorded_work_starts_with_a_full_budget():
    state = {"started_at": time.time() - 9999, "llm_calls_used": 0, "node_seconds": {}}
    _rebase(state)
    assert budget_left(state, max_calls=200, max_seconds=5400)
