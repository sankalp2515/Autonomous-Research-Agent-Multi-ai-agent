"""Phase 2 — the abstract profile steers retrieval, then audits it.

The profile is read off a title+abstract at screening (Phase 1b). It is a PRIOR,
never evidence: it decides what we READ and what we are entitled to SAY about
our own silence, never what counts as verified. Three properties follow, and all
three are pinned here:

  2a  a paper is searched in ITS OWN words, not only the run's;
  2b  an axis the abstract advertises earns more depth, but never at the cost of
      another axis's floor;
  2c  a "not reported" verdict needs TWO witnesses to agree.

The safety direction matters more than the gain: every use below degrades toward
LESS confidence when the profile is absent or wrong.
"""

import time

import pytest

from app.agents import nodes
from app.retrieval.dimension import DimensionSpec, build_dimension_queries


# ── 2a — paper-specific retrieval vocabulary ──────────────────────────────

def _dim() -> DimensionSpec:
    return DimensionSpec(name="latency", kind="quantitative",
                         synonyms=["response time"], metrics=["ms"])


def test_paper_vocabulary_becomes_its_own_query_angle():
    """The paper says 'MuSiQue' and 'exact match'; the run's schema does not."""
    profile = {"named_metrics": ["exact match"], "named_datasets": ["MuSiQue"],
               "named_systems": ["LightRAG"], "likely_dimensions": []}
    queries = build_dimension_queries(_dim(), ["GraphRAG"], "objective", profile)

    profile_angles = [q for q in queries if q.purpose == "profile"]
    assert len(profile_angles) == 1, "the paper's own vocabulary is not searched"
    text = profile_angles[0].text
    assert "MuSiQue" in text and "exact match" in text
    assert text.startswith("latency"), "the angle must stay anchored to the axis"


def test_paper_systems_join_the_entity_angle():
    """A comparative sentence names the systems as THIS paper names them."""
    profile = {"named_systems": ["HippoRAG2"]}
    queries = build_dimension_queries(_dim(), ["GraphRAG"], "", profile)

    entity = next(q for q in queries if q.purpose == "entities")
    assert "HippoRAG2" in entity.text and "GraphRAG" in entity.text


def test_absent_profile_changes_nothing():
    """Degradation is the default: no profile == the previous behaviour."""
    before = build_dimension_queries(_dim(), ["GraphRAG"], "objective")
    after = build_dimension_queries(_dim(), ["GraphRAG"], "objective", {})
    assert [(q.text, q.weight, q.purpose) for q in before] \
        == [(q.text, q.weight, q.purpose) for q in after]


def test_query_construction_stays_deterministic():
    """Two runs of one question must retrieve identically (reproducibility)."""
    profile = {"named_metrics": ["F1", "exact match"],
               "named_datasets": ["HotpotQA", "MuSiQue"]}
    a = build_dimension_queries(_dim(), ["B", "A"], "obj", profile)
    b = build_dimension_queries(_dim(), ["B", "A"], "obj", profile)
    assert [q.text for q in a] == [q.text for q in b]


# ── 2c — the second witness ───────────────────────────────────────────────

@pytest.fixture
def state():
    return {
        "run_id": "r", "project_id": "p", "llm_calls_used": 0,
        "started_at": time.time(), "coverage_notes": [],
        "evidence_schema": {
            "required_dimensions": [
                {"name": "latency", "kind": "quantitative", "description": "",
                 "synonyms": [], "metrics": [], "location_hints": []}],
            "optional_dimensions": [], "entities": [],
        },
    }


def _row(doc_id: str = "d1") -> dict:
    """A study that filled nothing, with a thorough search behind it."""
    return {
        "doc_id": doc_id, "title": "A study", "year": 2026, "findings": [],
        "full_text": True,
        "coverage": {"latency": {"queries": 4, "examined": 30, "chunks": 8}},
        "probes": {"latency": {"state": nodes._CELL_NOT_REPORTED,
                               "reason": "the study does not report it"}},
    }


def test_abstract_advertising_the_axis_blocks_a_not_reported_verdict(state):
    """The core of 2c: two witnesses must AGREE before we speak about the study.

    Recovery concluded 'not reported' and the coverage record backs it — but
    this paper's abstract advertised latency. The likelier explanation is that
    OUR search missed it, so the verdict becomes one about Veriscope.
    """
    state["paper_profiles"] = {"d1": {"likely_dimensions": ["latency"]}}

    matrix = nodes._attach_cells(state, [_row()])

    cell = matrix[0]["cells"]["latency"]
    assert cell["state"] == nodes._CELL_UNCERTAIN
    assert cell["profile_conflict"] is True
    assert state["funnel"]["cells_profile_conflict"] == 1


def test_silent_abstract_leaves_not_reported_standing(state):
    """When both witnesses agree, the verdict about the study survives."""
    state["paper_profiles"] = {"d1": {"likely_dimensions": ["accuracy"]}}

    matrix = nodes._attach_cells(state, [_row()])

    assert matrix[0]["cells"]["latency"]["state"] == nodes._CELL_NOT_REPORTED
    assert state["funnel"]["cells_profile_conflict"] == 0


def test_unprofiled_paper_is_unaffected(state):
    """A paper that never went through the screen keeps the old behaviour."""
    state["paper_profiles"] = {}

    matrix = nodes._attach_cells(state, [_row()])

    assert matrix[0]["cells"]["latency"]["state"] == nodes._CELL_NOT_REPORTED


def test_the_conflict_never_manufactures_a_finding(state):
    """2c may only move a cell TOWARD uncertainty — never into 'reported'."""
    state["paper_profiles"] = {"d1": {"likely_dimensions": ["latency"]}}

    matrix = nodes._attach_cells(state, [_row()])

    assert matrix[0]["cells"]["latency"]["state"] != nodes._CELL_REPORTED
    assert state["funnel"]["cells_reported"] == 0
