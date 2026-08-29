"""P0-A — the per-question evidence schema.

Two properties matter and both are load-bearing elsewhere:

1. REPRODUCIBILITY. The schema decides what every paper is searched for and what
   every study is audited against. If it drifted between runs, two reports on the
   same question would not be comparable and a benchmark could not attribute a
   change to anything. So it is normalized to a canonical form.
2. HONEST DEGRADATION. If the schema cannot be derived, the pipeline must fall
   back to the previous single-query behaviour and SAY so — never silently
   produce an audit with an empty required set, which would make every cell look
   deliberately unmeasured.
"""

import time

from app.agents import nodes
from app.agents.schemas import EvidenceDimension, ResearchEvidenceSchema


def _state():
    return {"run_id": "r", "project_id": "p", "query": "compare GraphRAG vs RAG",
            "llm_calls_used": 0, "started_at": time.time(), "coverage_notes": [],
            "clarification": {"objective": "compare GraphRAG vs standard RAG",
                              "domain": "information retrieval",
                              "sub_questions": ["q1", "q2"]}}


def _schema():
    return ResearchEvidenceSchema(
        research_type="Comparison",
        entities=["GraphRAG", "VectorRAG", "graphrag"],
        required_dimensions=[
            EvidenceDimension(name="  Retrieval Latency ", kind="quant",
                              synonyms=["Response Time", "ms", "response time"],
                              metrics=["S", "ms"], location_hints=["Results"]),
            EvidenceDimension(name="generation accuracy", kind="quantitative",
                              synonyms=["F1", "accuracy"]),
        ],
        optional_dimensions=[EvidenceDimension(name="limitation",
                                               kind="qualitative")],
        context_variables=["Dataset", "dataset", "Baseline"],
    )


def test_normalization_is_canonical_and_deduplicated():
    s = _schema().normalized()
    assert s.research_type == "comparison"
    assert s.entities == ["graphrag", "vectorrag"]
    names = [d.name for d in s.required_dimensions]
    assert names == sorted(names) and "retrieval latency" in names
    lat = next(d for d in s.required_dimensions if d.name == "retrieval latency")
    assert lat.kind == "quantitative"
    assert lat.synonyms == ["ms", "response time"]      # deduped, sorted
    assert s.context_variables == ["baseline", "dataset"]


def test_the_same_schema_in_any_order_normalizes_identically():
    """Reproducibility: a model reordering its own output must not change the
    retrieval queries or the audit set."""
    a = _schema().normalized()
    shuffled = _schema()
    shuffled.required_dimensions.reverse()
    shuffled.entities.reverse()
    assert a.model_dump() == shuffled.normalized().model_dump()


def test_a_dimension_cannot_be_both_required_and_optional():
    s = ResearchEvidenceSchema(
        required_dimensions=[EvidenceDimension(name="latency")],
        optional_dimensions=[EvidenceDimension(name="latency")],
    ).normalized()
    assert [d.name for d in s.optional_dimensions] == []


async def test_the_node_stores_a_normalized_schema(monkeypatch):
    seen = {}

    async def fake_complete_json(_kind, prompt, _model, **kw):
        seen["temperature"] = kw.get("temperature")
        seen["prompt"] = prompt
        return _schema()

    monkeypatch.setattr(nodes, "_checkpoint", _noop)
    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    state = _state()
    await nodes.evidence_schema_node(state)
    # Reproducibility is bought with temperature 0; pinned here so a future
    # tweak cannot quietly reintroduce run-to-run drift.
    assert seen["temperature"] == 0.0
    # The schema is derived from the QUESTION, never hardcoded per domain.
    assert "compare GraphRAG vs RAG" in seen["prompt"]
    assert [d["name"] for d in state["evidence_schema"]["required_dimensions"]] == [
        "generation accuracy", "retrieval latency"]
    assert state["llm_calls_used"] == 1


async def test_the_node_is_idempotent_across_replans(monkeypatch):
    """A replan must not re-derive the audit set underneath studies already
    extracted against it."""
    calls = {"n": 0}

    def counting(*_a, **_kw):
        calls["n"] += 1
        raise AssertionError("the schema was re-derived on a replan pass")

    monkeypatch.setattr(nodes, "_checkpoint", _noop)
    monkeypatch.setattr(nodes, "complete_json", counting)
    state = _state()
    state["evidence_schema"] = {"research_type": "comparison",
                                "required_dimensions": [{"name": "latency"}]}
    await nodes.evidence_schema_node(state)
    assert calls["n"] == 0


async def test_a_failed_derivation_degrades_loudly(monkeypatch):
    async def boom(*_a, **_kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(nodes, "_checkpoint", _noop)
    monkeypatch.setattr(nodes, "complete_json", boom)
    state = _state()
    await nodes.evidence_schema_node(state)

    assert state["evidence_schema"] == {}
    assert any("single general query" in n for n in state["coverage_notes"]), (
        "the run degraded to the legacy path without telling the reader")


async def test_an_empty_required_set_counts_as_a_failure(monkeypatch):
    """A schema with nothing required would make every cell unauditable while
    looking like a successful derivation."""
    monkeypatch.setattr(nodes, "_checkpoint", _noop)
    monkeypatch.setattr(nodes, "complete_json",
                        _returning(ResearchEvidenceSchema(required_dimensions=[])))
    state = _state()
    await nodes.evidence_schema_node(state)
    assert state["evidence_schema"] == {}


async def _noop(*_a, **_kw):
    return None


def _returning(value):
    async def _fn(*_a, **_kw):
        return value
    return _fn
