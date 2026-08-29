"""P0-C/D — the completeness audit, and the four honest cell states.

WHAT WENT WRONG BEFORE. The matrix had two states: a finding, or an em-dash
captioned "this study did not report that dimension, never that we failed to
look". On the calibration run about half the em-dashes were retrieval failures,
so the report was publishing OUR limitation as a fact about the literature.

These tests pin the rule that replaces it: a cell may only be called
`not_reported` when the search behind it was substantial enough for silence to
mean something. Every other unresolved case is `extraction_uncertain`, which is a
statement about Veriscope, not about the paper. The bias is deliberate and the
tests below are written to fail if anyone ever "improves" the fill rate by
relaxing it.
"""

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from app.agents import nodes
from app.agents.schemas import DimensionProbe, DimensionProbeResult
from app.retrieval.dimension import DimensionHits, DimensionSpec

CHUNK_TEXT = ("End-to-end response time was measured at 9.03 s for the graph "
              "pipeline against 1.20 s for the vector baseline.")
NO_LATENCY_TEXT = ("We leave a systematic efficiency analysis to future work "
                   "and report accuracy only.")


@dataclass
class _Chunk:
    chunk_id: str
    text: str
    document_title: str = "A Paper"
    section: str = "Efficiency Analysis"
    page_start: int = 7
    page_end: int = 7
    abstract_only: bool = False


class _FakeSession:
    def __init__(self):
        self.added = []
        self._n = 0

    def add(self, row):
        self._n += 1
        if getattr(row, "id", None) is None:
            row.id = f"row{self._n}"
        self.added.append(row)

    async def flush(self):
        return None


LATENCY = DimensionSpec(name="retrieval latency", kind="quantitative",
                        synonyms=["response time"], metrics=["s", "ms"])


def _state(schema=True):
    st = {"run_id": "r", "project_id": "p", "llm_calls_used": 0,
          "started_at": time.time(), "coverage_notes": [], "funnel": {}}
    if schema:
        st["evidence_schema"] = {
            "research_type": "comparison", "entities": ["graphrag"],
            "required_dimensions": [
                {"name": "retrieval latency", "kind": "quantitative",
                 "synonyms": ["response time"], "metrics": ["s"],
                 "location_hints": ["efficiency"], "not_applicable_when": ""},
                {"name": "generation accuracy", "kind": "quantitative",
                 "synonyms": ["accuracy"], "metrics": ["f1"],
                 "location_hints": ["results"], "not_applicable_when": ""},
            ],
            "optional_dimensions": [], "context_variables": ["dataset"],
        }
    return st


def _row(findings=None):
    return {"doc_id": "d1", "title": "A Paper", "year": 2026,
            "frameworks": ["GraphRAG"], "baselines": [], "datasets": [],
            "findings": findings if findings is not None else [
                {"dimension": "generation accuracy", "text": "acc", "metric": "F1",
                 "value": "89%", "chunk_id": "c1", "quote": "q", "claim_id": "cl1",
                 "nli_label": "entailment", "nli_score": 0.9}],
            "coverage": {}, "full_text": True}


@pytest.fixture
def patched(monkeypatch):
    """Wire the recovery pass to a fixed paper + a scriptable probe response."""
    import app.retrieval.dimension as dim_mod
    session = _FakeSession()
    box = {"probe": None, "chunks": [_Chunk("c_lat", CHUNK_TEXT)],
           "coverage": {"retrieval latency": DimensionHits(
               "retrieval latency", ["q1", "q2", "q3"], [], examined=11)}}

    @asynccontextmanager
    async def fake_scope():
        yield session

    async def fake_retrieve_by_dimension(*_a, **_kw):
        return box["chunks"], box["coverage"]

    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return box["probe"]

    monkeypatch.setattr(nodes, "session_scope", fake_scope)
    monkeypatch.setattr(dim_mod, "retrieve_by_dimension", fake_retrieve_by_dimension)
    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    box["session"] = session
    return box


async def test_a_recovered_finding_is_verified_and_persisted(patched):
    """The recall win — but it still has to pass the SAME gate as everything."""
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="reported",
        text="The graph pipeline answered in 9.03 s versus 1.20 s for vectors.",
        metric="s", value="9.03 s", chunk_id="c_lat",
        quote="response time was measured at 9.03 s")])

    row = _row()
    verdicts = await nodes._recover_one_study(_state(), row, [LATENCY], "objective")

    assert verdicts["retrieval latency"]["state"] == "reported"
    assert verdicts["retrieval latency"]["recovered"] is True
    recovered = [f for f in row["findings"] if f.get("recovered")]
    assert len(recovered) == 1 and recovered[0]["dimension"] == "retrieval latency"
    # G2: a rendered cell must resolve to a real Claim + ClaimEvidence row.
    kinds = [type(r).__name__ for r in patched["session"].added]
    assert "Claim" in kinds and "ClaimEvidence" in kinds


async def test_a_fabricated_recovery_is_dropped_not_promoted(patched):
    """Recovery must not become a back door around the verification gate."""
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="reported",
        text="Latency was 40 ms.", metric="ms", value="40 ms", chunk_id="c_lat",
        quote="latency was a blazing 40 ms in all conditions")])

    row = _row()
    verdicts = await nodes._recover_one_study(_state(), row, [LATENCY], "objective")

    assert verdicts["retrieval latency"]["state"] == "extraction_uncertain", (
        "a claim that failed the gate was still recorded as evidence")
    assert not [f for f in row["findings"] if f.get("recovered")]
    assert "Claim" not in [type(r).__name__ for r in patched["session"].added]


async def test_not_reported_requires_real_search_coverage(patched):
    """With full text and a real search behind it, silence is a finding."""
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_reported",
        rationale="the paper reports accuracy only")])

    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "not_reported"


async def test_thin_coverage_downgrades_not_reported_to_uncertain(patched):
    """The whole point: we may not conclude absence from a search we didn't do."""
    patched["coverage"] = {"retrieval latency": DimensionHits(
        "retrieval latency", ["only-one-query"], [], examined=1)}
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_reported",
        rationale="I did not see it")])

    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "extraction_uncertain"


async def test_abstract_only_papers_can_never_be_called_silent(patched):
    """We never had the paper's results, so we cannot report on their absence."""
    patched["chunks"] = [_Chunk("c_abs", "Abstract: we study graph retrieval.",
                                abstract_only=True)]
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_reported",
        rationale="not in the abstract")])

    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "extraction_uncertain"
    assert "full text" in verdicts["retrieval latency"]["reason"]


async def test_an_explicit_statement_of_absence_is_quote_checked(patched):
    """A paper saying so outright is the strongest form of 'not reported' — but
    the quote still has to actually be in the cited chunk."""
    patched["chunks"] = [_Chunk("c_none", NO_LATENCY_TEXT, section="Conclusion")]
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_reported",
        chunk_id="c_none", quote="leave a systematic efficiency analysis to future work",
        rationale="explicitly deferred")])

    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    cell = verdicts["retrieval latency"]
    assert cell["state"] == "not_reported" and cell["chunk_id"] == "c_none"


async def test_an_invented_absence_quote_is_not_attached(patched):
    patched["chunks"] = [_Chunk("c_none", NO_LATENCY_TEXT, section="Conclusion")]
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_reported",
        chunk_id="c_none", quote="we deliberately omitted all timing experiments",
        rationale="explicitly deferred")])

    cell = (await nodes._recover_one_study(
        _state(), _row(), [LATENCY], "objective"))["retrieval latency"]
    assert cell["state"] == "not_reported"
    assert "quote" not in cell, "an unmatched quote was attached as grounding"


async def test_not_applicable_is_preserved(patched):
    patched["probe"] = DimensionProbeResult(probes=[DimensionProbe(
        dimension="retrieval latency", status="not_applicable",
        rationale="this is a survey; it runs no system of its own")])

    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "not_applicable"


async def test_a_silent_probe_leaves_the_cell_unresolved(patched):
    """A probe that simply ignores an axis must not be read as a denial."""
    patched["probe"] = DimensionProbeResult(probes=[])
    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "extraction_uncertain"


async def test_an_already_probed_axis_is_not_probed_again(patched):
    """A replan re-enters extraction. Re-chasing an axis we already resolved
    would re-pay the call to reach the same verdict — on the budget the replan
    needs for the NEW papers it went and found."""
    patched["probe"] = DimensionProbeResult(probes=[])
    row = _row()
    row["probes"] = {"retrieval latency": {"state": "not_reported"}}
    verdicts = await nodes._recover_one_study(_state(), row, [LATENCY], "objective")
    assert verdicts == {}


async def test_a_failed_probe_call_leaves_every_cell_unresolved(patched, monkeypatch):
    async def boom(*_a, **_kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(nodes, "complete_json", boom)
    verdicts = await nodes._recover_one_study(_state(), _row(), [LATENCY], "objective")
    assert verdicts["retrieval latency"]["state"] == "extraction_uncertain"


# ── cell-state assembly ──────────────────────────────────────────────────

def test_every_required_dimension_gets_an_explicit_state():
    state = _state()
    matrix = [_row()]
    nodes._attach_cells(state, matrix)

    cells = matrix[0]["cells"]
    assert cells["generation accuracy"]["state"] == "reported"
    assert cells["generation accuracy"]["claim_ids"] == ["cl1"]
    # Never filled, never probed -> ours to own.
    assert cells["retrieval latency"]["state"] == "extraction_uncertain"


def test_an_unprobed_cell_is_never_called_not_reported():
    """Recovery off / budget-capped / crashed must not silently become a claim
    about the study — this is the exact regression the rework exists to kill."""
    state = _state()
    matrix = [_row()]
    nodes._attach_cells(state, matrix)
    assert matrix[0]["cells"]["retrieval latency"]["state"] != "not_reported"


def test_cell_tallies_are_reported_in_the_funnel():
    state = _state()
    matrix = [_row(), _row()]
    matrix[1]["probes"] = {"retrieval latency": {"state": "not_reported"}}
    nodes._attach_cells(state, matrix)

    f = state["funnel"]
    assert f["cells_total"] == 4                      # 2 studies x 2 required
    assert f["cells_reported"] == 2                   # accuracy in both
    assert f["cells_not_reported"] == 1
    assert f["cells_uncertain"] == 1
    assert f["required_dimensions"] == ["retrieval latency", "generation accuracy"]


def test_every_displayed_column_is_audited_even_without_a_schema():
    """The audit set IS the grid the reader sees.

    It used to be the schema's required axes only, while the matrix rendered the
    top-N axes by frequency. Any displayed column outside the required set got no
    state and fell through to a bare em-dash — 24 of them in a live report,
    reintroducing the silent-empty-cell this whole rework exists to delete. With
    no schema at all, the observed dimensions are still audited, and anything
    unresolved is OURS (extraction_uncertain), never a claim about the study.
    """
    state = _state(schema=False)
    matrix = [_row()]
    nodes._attach_cells(state, matrix)

    assert matrix[0]["cells"]["generation accuracy"]["state"] == "reported"
    assert state["funnel"]["cells_total"] == 1
    assert state["funnel"]["required_dimensions"] == ["generation accuracy"]


def test_a_displayed_extra_column_gets_a_state_not_an_em_dash():
    """A column the reader can see and the pipeline never checked is a column of
    unexplained dashes — the exact regression this pins."""
    state = _state()                       # schema requires latency + accuracy
    row = _row()
    row["findings"].append(
        {"dimension": "limitation", "text": "t", "metric": "", "value": "",
         "chunk_id": "c2", "quote": "q", "claim_id": "cl2",
         "nli_label": "entailment", "nli_score": 0.9})
    other = _row()                          # a study with no 'limitation' finding
    other["doc_id"] = "d2"
    nodes._attach_cells(state, [row, other])

    # 'limitation' is displayed (a study reports it), so it must be audited...
    assert "limitation" in state["funnel"]["required_dimensions"]
    # ...and the study that did not fill it gets an owned state, not a dash.
    assert other["cells"]["limitation"]["state"] == "extraction_uncertain"
