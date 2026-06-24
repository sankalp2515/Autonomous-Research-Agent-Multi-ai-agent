"""Pipeline state shared across LangGraph nodes.

Plain JSON-serializable dict (TypedDict) so every node boundary can be
checkpointed verbatim into runs.checkpoint and resumed after a crash.
"""

import time
from typing import Any, TypedDict


class SectionState(TypedDict, total=False):
    heading: str
    sub_question: str
    guidance: str
    status: str               # pending | verified | gap
    track: str                # academic | technical - evidence classes never mix
    claim_ids: list[str]
    gap_note: str
    regens_used: int


class PipelineState(TypedDict, total=False):
    run_id: str
    project_id: str
    query: str

    clarification: dict[str, Any]
    plan: dict[str, Any]

    paper_doc_ids: list[str]
    repo_doc_ids: list[str]
    blog_doc_ids: list[str]
    coverage_notes: list[str]      # honest record of failed/empty sources

    outline_title: str
    sections: list[SectionState]

    replan_targets: list[str]      # sub-questions needing a replan
    replans_used: dict[str, int]

    llm_calls_used: int
    started_at: float
    report_id: str
    final_status: str
    rejected: str  # set by clarify if the query isn't a research question


def new_state(run_id: str, project_id: str, query: str) -> PipelineState:
    return PipelineState(
        run_id=run_id, project_id=project_id, query=query,
        coverage_notes=[], sections=[], replan_targets=[], replans_used={},
        llm_calls_used=0, started_at=time.time(),
    )


def budget_left(state: PipelineState, max_calls: int, max_seconds: int) -> bool:
    if state.get("llm_calls_used", 0) >= max_calls:
        return False
    if time.time() - state.get("started_at", time.time()) >= max_seconds:
        return False
    return True
