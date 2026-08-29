"""Regression tests for the run clock and the typed live-feed events.

Two failures on the research screen this pins:

1. The UI read the elapsed time from `budgets_spent["seconds"]`, which the
   pipeline only rewrites at a NODE CHECKPOINT. Inside `research` — minutes of
   downloading and parsing — the number froze, so a healthy run read as hung
   and a finished one under-reported itself by the length of its last node.
   `_run_clock` computes the duration server-side against one reference `now`.

2. SQLite drops the tzinfo that `DateTime(timezone=True)` carries on Postgres.
   A naive value there is UTC that lost its label, never local time; reading it
   as local put the clock out by whole hours. `_epoch` fixes the tz to UTC.
"""

from datetime import datetime, timedelta, timezone

from app.agents.nodes import _NODE_MSG
from app.api.routes import _epoch, _run_clock
from app.db.models import Run


def _run(**kw) -> Run:
    now = datetime.now(timezone.utc)
    base = dict(id="r1", project_id="p1", query="q", status="running",
                created_at=now - timedelta(seconds=90), updated_at=now,
                budgets_spent={"seconds": 5})
    base.update(kw)
    return Run(**base)


def test_naive_timestamp_is_read_as_utc_not_local():
    aware = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 8, 15, 12, 0, 0)
    assert _epoch(naive) == _epoch(aware)


def test_running_clock_ignores_the_frozen_checkpoint_value():
    clock = _run_clock(_run())
    # 90s of real wall time, not the 5s the last checkpoint happened to record.
    assert 88 <= clock["elapsed_seconds"] <= 95
    assert clock["running"] is True
    assert clock["started_epoch"] > 0


def test_finished_run_is_measured_start_to_finish():
    start = datetime(2026, 8, 15, 9, 0, 0, tzinfo=timezone.utc)
    clock = _run_clock(_run(status="completed", created_at=start,
                            updated_at=start + timedelta(seconds=3600),
                            budgets_spent={"seconds": 2400}))
    assert clock["running"] is False
    # The last node ran for 20 more minutes after the final checkpoint; the
    # report took an hour and must not claim 40 minutes.
    assert clock["elapsed_seconds"] == 3600


def test_clock_never_goes_negative_on_skew():
    now = datetime.now(timezone.utc)
    clock = _run_clock(_run(created_at=now + timedelta(seconds=30)))
    assert clock["elapsed_seconds"] >= 0


def test_every_node_message_is_researcher_facing():
    """The stepper and feed label nodes for a reader, so every graph node the
    pipeline can sit in needs a sentence — a missing one shows a raw node id."""
    from app.agents.graph import build_pipeline  # noqa: F401  (import guard)

    for node in ("clarify", "plan", "evidence_schema", "research",
                 "extract_evidence", "report_architect", "draft_sections",
                 "assemble", "build_graph"):
        assert _NODE_MSG.get(node), f"no live-feed message for node {node}"


def test_every_progress_event_is_typed_at_the_publish_site():
    """`kind` is what the live feed groups, filters and colours on.

    The UI used to infer the category by pattern-matching our own prose, so
    rewording a message silently moved an event into the wrong filter (or, for
    a gate refusal, coloured a refusal as progress). Typing happens where the
    event is published; an untyped publish site is the regression.
    """
    import ast
    import pathlib

    for path in ("app/agents/nodes.py", "app/agents/graph.py"):
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            fn = call.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name != "publish_progress" or len(call.args) < 2:
                continue
            payload = call.args[1]
            if not isinstance(payload, ast.Dict):
                continue  # built elsewhere; not a literal we can check here
            keys = {k.value for k in payload.keys
                    if isinstance(k, ast.Constant)}
            assert "kind" in keys, (
                f"{path}:{call.lineno} publishes an untyped progress event"
            )
