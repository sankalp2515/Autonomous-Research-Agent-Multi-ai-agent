"""Phase 2 — report structure must be chosen AFTER the evidence, from it.

The old outline node ran on counts alone ("10 papers, 0 repos") and was told
"each section must map to one sub-question", so the report's shape was fixed at
clarify time — before a single paper had been found — and merely relabelled once
the evidence arrived. These tests pin the two properties that make the new node
a report ARCHITECT rather than a relabeller: it is shown what was actually
found, and it is free to structure the report around that.
"""

import time

import pytest

from app.agents import nodes
from app.agents.schemas import Outline, OutlineSection


def _state(matrix=None):
    return {
        "run_id": "r", "project_id": "p", "query": "compare GraphRAG vs RAG",
        "llm_calls_used": 0, "started_at": time.time(), "coverage_notes": [],
        "clarification": {"objective": "compare GraphRAG vs standard RAG",
                          "sub_questions": ["q1", "q2", "q3", "q4", "q5", "q6"]},
        "paper_doc_ids": ["d1", "d2"], "repo_doc_ids": [], "blog_doc_ids": [],
        "evidence_matrix": matrix if matrix is not None else [],
    }


def _matrix():
    return [
        {"doc_id": "d1", "title": "Do We Still Need GraphRAG?", "year": 2026,
         "frameworks": ["GraphRAG", "LightRAG"], "baselines": ["NaiveRAG"],
         "datasets": ["HotpotQA"],
         "findings": [
             {"dimension": "multi-hop accuracy", "text": "t1", "metric": "F1",
              "value": "+27.23", "chunk_id": "c1", "quote": "q", "claim_id": "cl1",
              "nli_label": "entailment", "nli_score": 0.99},
             {"dimension": "latency", "text": "t2", "metric": "s", "value": "9.03s",
              "chunk_id": "c2", "quote": "q", "claim_id": "cl2",
              "nli_label": "entailment", "nli_score": 0.98},
         ]},
        {"doc_id": "d2", "title": "When to use Graphs in RAG", "year": 2025,
         "frameworks": ["HippoRAG2"], "baselines": [], "datasets": ["MuSiQue"],
         "findings": [
             {"dimension": "multi-hop accuracy", "text": "t3", "metric": "acc",
              "value": "89%", "chunk_id": "c3", "quote": "q", "claim_id": "cl3",
              "nli_label": "entailment", "nli_score": 0.97},
         ]},
    ]


@pytest.fixture
def captured(monkeypatch):
    box = {}

    async def fake_complete_json(_kind, prompt, _schema, **kw):
        box["prompt"] = prompt
        box["system"] = kw.get("system", "")
        return Outline(title="A Title", sections=[
            OutlineSection(heading="What the evidence says",
                           sub_question="Does GraphRAG beat RAG?",
                           section_type="bottom_line",
                           retrieval_brief="GraphRAG vs NaiveRAG multi-hop F1 HotpotQA"),
            OutlineSection(heading="Where it costs you",
                           sub_question="What does it cost?",
                           section_type="tradeoff_analysis",
                           retrieval_brief="GraphRAG latency token cost indexing overhead"),
        ])

    # The @_timed wrapper checkpoints to Postgres/Redis. Those are integration
    # concerns, not this unit's; left live they leak a connection across event
    # loops and the SECOND test in the file dies with "Event loop is closed".
    async def no_checkpoint(*_a, **_kw):
        return None

    monkeypatch.setattr(nodes, "_checkpoint", no_checkpoint)
    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    return box


async def test_architect_is_shown_the_evidence_that_was_found(captured):
    """The whole point of the phase: structure chosen with the evidence in view."""
    await nodes.report_architect_node(_state(_matrix()))
    prompt = captured["prompt"]

    assert "EVIDENCE ACTUALLY FOUND" in prompt
    # Dimensions carry their study counts, so the architect can tell a
    # well-measured axis from a one-off remark.
    assert "multi-hop accuracy (2)" in prompt
    assert "latency (1)" in prompt
    # The systems under comparison, and real study titles.
    assert "GraphRAG" in prompt and "HippoRAG2" in prompt
    assert "Do We Still Need GraphRAG?" in prompt


async def test_sections_need_not_mirror_the_sub_questions(captured):
    """6 research questions may become 2 sections if that fits the evidence."""
    state = _state(_matrix())
    await nodes.report_architect_node(state)

    assert len(state["clarification"]["sub_questions"]) == 6
    assert len(state["sections"]) == 2, "structure is still shackled to the plan"
    assert [s["section_type"] for s in state["sections"]] == [
        "bottom_line", "tradeoff_analysis"]


async def test_retrieval_brief_drives_corpus_search(captured):
    """Sections must search the corpus with paper vocabulary, not chat phrasing."""
    state = _state(_matrix())
    await nodes.report_architect_node(state)

    first = state["sections"][0]
    # sub_question is what the drafter retrieves on...
    assert first["sub_question"] == "GraphRAG vs NaiveRAG multi-hop F1 HotpotQA"
    # ...and the reader-facing framing is preserved separately.
    assert first["framing"] == "Does GraphRAG beat RAG?"


async def test_falls_back_gracefully_with_no_matrix(captured):
    """An empty matrix must still produce a report, structured on the questions."""
    state = _state([])
    await nodes.report_architect_node(state)

    assert "No structured evidence was extracted" in captured["prompt"]
    assert len(state["sections"]) == 2
    assert all(s["status"] == "pending" for s in state["sections"])


async def test_replan_pass_keeps_the_existing_structure(captured):
    """A replan re-runs failed sections; it must not re-architect the report."""
    state = _state(_matrix())
    state["sections"] = [{"heading": "existing", "status": "gap"}]
    state["replan_targets"] = ["q1"]
    await nodes.report_architect_node(state)

    assert state["sections"] == [{"heading": "existing", "status": "gap"}]
    assert "prompt" not in captured, "the architect burned a call on a replan pass"
