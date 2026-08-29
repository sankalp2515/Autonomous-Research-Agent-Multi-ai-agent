"""P2 J/K/L — gaps with an evidence basis, and a genre-aware architecture.

A literature review that ends on "more research is needed" has told the reader
nothing they could not have guessed. A gap is only information when it names
what is missing and shows the count that makes it missing. And a comparison
question, a decision question and a mechanism question want different reports —
the old architect received the same instruction for all of them, so every run
produced the same five-section literature summary.
"""

import time

import pytest

from app.agents import nodes
from app.agents.schemas import Outline, OutlineSection
from app.agents.synthesis import (
    GAP_CONTESTED, GAP_NOT_COMPARABLE, GAP_SINGLE_STUDY, GAP_UNDER_MEASURED,
    research_gaps, study_characteristics, synthesize,
)


def _f(dim, value, *, dataset="HotpotQA", metric="F1", model="", task="qa"):
    return {"dimension": dim, "metric": metric, "value": value, "claim_id": "c",
            "text": "t", "chunk_id": "ch", "quote": "q",
            "context": {"dataset": dataset, "task": task, "baseline": "",
                        "model": model, "condition": ""}}


def _corpus(n=8):
    return [{"doc_id": f"d{i}", "title": f"Study {i}", "year": 2024 + (i % 3),
             "frameworks": ["GraphRAG"], "baselines": ["VectorRAG"],
             "datasets": ["HotpotQA"], "findings": [_f("accuracy", f"8{i}.0%")]}
            for i in range(1, n + 1)]


def _gaps(matrix):
    return {g["kind"]: g for g in synthesize(matrix)["gaps"]}


# ── J: gaps ──────────────────────────────────────────────────────────────

def test_an_axis_one_study_touched_is_a_named_gap():
    m = _corpus()
    m[0]["findings"].append(_f("production cost", "12.5 USD",
                               dataset="internal", metric="cost"))
    g = _gaps(m)[GAP_SINGLE_STUDY]
    assert g["dimension"] == "production cost" and g["severity"] == "high"
    assert "one of 8 studies" in g["basis"]


def test_an_under_measured_axis_names_both_counts():
    """The example from the brief: 14 measure accuracy, 3 measure latency."""
    m = _corpus(10)
    for i in range(3):
        m[i]["findings"].append(_f("latency", f"{100 + i * 40} ms",
                                   dataset=f"Set{i}", metric="latency"))
    g = _gaps(m)[GAP_UNDER_MEASURED]
    assert g["dimension"] == "latency"
    assert "10 of 10" in g["basis"] and "only 3" in g["basis"]


def test_measured_by_many_but_never_comparably_is_its_own_gap():
    """The gap a fill-rate metric hides: the column looks full, the numbers
    cannot be pooled."""
    m = _corpus(6)
    for i in range(5):
        m[i]["findings"].append(_f("latency", f"{100 + i * 5} ms",
                                   dataset=f"Bench{i}", metric="latency"))
    g = _gaps(m)[GAP_NOT_COMPARABLE]
    assert "no two measured it the same way" in g["basis"]
    assert "shared benchmark is missing, not" in g["basis"]


def test_a_contested_axis_asks_for_a_controlled_comparison():
    m = _corpus(4)
    m[0]["findings"].append(_f("latency", "100 ms", metric="latency"))
    m[1]["findings"].append(_f("latency", "900 ms", metric="latency"))
    g = _gaps(m)[GAP_CONTESTED]
    assert g["severity"] == "high"
    assert "not another datapoint" in g["basis"]


def test_every_gap_carries_counts_and_no_generic_filler():
    m = _corpus(9)
    m[0]["findings"].append(_f("production cost", "12 USD", dataset="x", metric="cost"))
    for g in synthesize(m)["gaps"]:
        assert any(ch.isdigit() for ch in g["basis"]), g
        assert "more research is needed" not in g["basis"].lower()


def test_a_well_covered_corpus_reports_no_gaps():
    assert synthesize(_corpus(8))["gaps"] == []


def test_gaps_are_empty_without_evidence():
    assert research_gaps({"dimensions": [], "studies_total": 0}) == []


# ── L: study characteristics ─────────────────────────────────────────────

def test_study_characteristics_describe_the_sample():
    m = _corpus(5)
    m[0]["findings"][0]["context"]["model"] = "GPT-4o"
    ch = study_characteristics(m, full_text_count=4)

    assert ch["studies"] == 5 and ch["full_text"] == 4
    assert ch["year_span"] == {"min": 2024, "max": 2026}
    assert ch["frameworks"][0] == {"name": "GraphRAG", "studies": 5}
    assert ch["datasets"][0]["name"] == "HotpotQA"
    assert ch["models"][0]["name"] == "GPT-4o"


def test_framework_concentration_is_reported():
    """If one system dominates the corpus, every conclusion is really a
    conclusion about that system — the reader should see that up front."""
    assert study_characteristics(_corpus(4))["framework_concentration"] == 1.0


def test_characteristics_of_an_empty_corpus_do_not_crash():
    ch = study_characteristics([])
    assert ch["studies"] == 0 and ch["year_span"] is None


# ── K: genre ─────────────────────────────────────────────────────────────
#
# These now exercise the architect as the FALLBACK path. The outline is normally
# built from the evidence schema's axes (see test_axis_sections.py); the
# architect runs only when a run has no usable schema, and its genre behaviour
# still has to hold there — that is the path a degraded run takes, and a
# degraded run is exactly when a sensible default matters most.
#
# `required_dimensions` is therefore left EMPTY here on purpose: supplying axes
# would take the schema-driven path and never reach the architect at all.

def _state(research_type="comparison", entities=("GraphRAG", "RAG")):
    return {
        "run_id": "r", "project_id": "p", "query": "q", "llm_calls_used": 0,
        "started_at": time.time(), "coverage_notes": [],
        "clarification": {"objective": "o", "sub_questions": ["a", "b"]},
        "paper_doc_ids": ["d1"], "repo_doc_ids": [], "blog_doc_ids": [],
        "evidence_matrix": [], "synthesis": {},
        "evidence_schema": {"research_type": research_type,
                            "entities": list(entities),
                            "required_dimensions": [], "optional_dimensions": []},
    }


@pytest.fixture
def captured(monkeypatch):
    box = {}

    async def fake_complete_json(_kind, prompt, _schema, **kw):
        box["prompt"] = prompt
        box["temperature"] = kw.get("temperature")
        return Outline(title="T", sections=[
            OutlineSection(heading="H", sub_question="Q", section_type="bottom_line",
                           retrieval_brief="brief")])

    async def no_checkpoint(*_a, **_kw):
        return None

    monkeypatch.setattr(nodes, "_checkpoint", no_checkpoint)
    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    return box


@pytest.mark.parametrize("genre,marker", [
    ("comparison", "when each approach wins"),
    ("decision", "the conditions under which the recommendation flips"),
    ("evolution", "problems that survived every generation"),
    ("mechanism", "boundary conditions where it stops holding"),
])
async def test_each_question_type_gets_a_different_report_shape(captured, genre, marker):
    state = _state(genre)
    await nodes.report_architect_node(state)
    assert "RESEARCH GENRE: this question is a " + genre.upper() in captured["prompt"]
    assert marker in captured["prompt"]
    assert state["report_genre"] == genre


async def test_the_spine_is_offered_as_an_example_not_a_template(captured):
    await nodes.report_architect_node(_state("decision"))
    assert "WORKED EXAMPLE, not a template" in captured["prompt"]


async def test_architecture_is_deterministic(captured):
    """Two runs of one question must produce the same structure, or nothing
    downstream is comparable between them."""
    await nodes.report_architect_node(_state())
    assert captured["temperature"] == 0.0


async def test_an_unknown_research_type_falls_back_on_the_entities(captured):
    """Two things under study -> a comparison; one -> a survey. Never a crash."""
    s1 = _state("something-new", entities=("A", "B"))
    await nodes.report_architect_node(s1)
    assert s1["report_genre"] == "comparison"

    s2 = _state("", entities=("A",))
    await nodes.report_architect_node(s2)
    assert s2["report_genre"] == "survey"


async def test_gaps_are_given_to_the_architect_as_structure(captured):
    """An axis one study touched is a gap to name, not a section to attempt."""
    state = _state()
    state["synthesis"] = {"gaps": [
        {"basis": "exactly one of 8 studies reports production cost"}]}
    await nodes.report_architect_node(state)
    assert "GAPS ALREADY IDENTIFIED" in captured["prompt"]
    assert "production cost" in captured["prompt"]
