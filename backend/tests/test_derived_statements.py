"""Phase 3 — D (derived) statements and their gate.

A D sentence says something no single paper says and no quote can ground: how
many studies measured an axis, how many measured it the same way, which pairs
disagree. Its gate is therefore not entailment but RECOMPUTATION — the sentence
is produced by template from numbers `synthesize` already computed, with no LLM
in the path, so re-running the function reproduces it exactly.

Three properties make that gate real, and all three are pinned here:

  1. determinism — same matrix in, same sentences out;
  2. provenance  — every statement names the rows its arithmetic ran over, and a
                   statement that cannot name them is not emitted;
  3. restraint   — a D sentence may state the counts and nothing beyond them.
                   "No two of the 12 studies measured this the same way" is
                   arithmetic; "the field lacks a shared benchmark" is an
                   inference about the world, which is an I sentence, and I is
                   not shipped.
"""

from app.agents.statements import (
    TYPE_DERIVED,
    composition,
    derive_statements,
)
from app.agents.synthesis import synthesize


def _finding(dimension: str, value: str, **context) -> dict:
    ctx = {"dataset": "", "task": "", "baseline": "", "model": "", "condition": ""}
    ctx.update(context)
    return {"dimension": dimension, "metric": dimension, "value": value,
            "text": f"{dimension} was {value}", "claim_id": f"c-{dimension}-{value}",
            "chunk_id": "chunk", "quote": "q", "context": ctx}


def _study(doc_id: str, findings: list[dict]) -> dict:
    return {"doc_id": doc_id, "title": f"Study {doc_id}", "year": 2026,
            "findings": findings, "full_text": True}


def _run(matrix: list[dict]) -> list[dict]:
    return derive_statements(synthesize(matrix), matrix)


def test_every_statement_is_typed_and_carries_its_rows():
    matrix = [_study(f"d{i}", [_finding("latency", f"{i}.0s", dataset="HotpotQA")])
              for i in range(1, 5)]

    statements = _run(matrix)

    assert statements, "a four-study axis produced no derived sentence"
    for s in statements:
        assert s["type"] == TYPE_DERIVED
        assert s["doc_ids"], f"no provenance on: {s['text']}"
        assert all(d.startswith("d") for d in s["doc_ids"])
        assert s["text"].endswith("."), s["text"]


def test_the_coverage_sentence_states_the_real_counts():
    matrix = [_study("d1", [_finding("latency", "1.0s")]),
              _study("d2", [_finding("latency", "2.0s")]),
              _study("d3", [_finding("accuracy", "90%")])]

    texts = [s["text"] for s in _run(matrix)]

    assert any("2 of the 3 studies report latency." == t for t in texts), texts


def test_incomparability_is_stated_as_prose_not_left_in_a_column():
    """The fact a fill-rate metric hides completely, said in words."""
    matrix = [_study(f"d{i}", [_finding("accuracy", "89.0%", dataset=f"Set{i}")])
              for i in range(1, 6)]

    texts = " ".join(s["text"] for s in _run(matrix))

    assert "No two of them measured accuracy the same way" in texts
    assert "cannot be pooled or ranked" in texts


def test_a_single_study_axis_says_nothing_can_corroborate_it():
    matrix = [_study("d1", [_finding("cost", "$5")]),
              _study("d2", [_finding("accuracy", "90%")])]

    texts = " ".join(s["text"] for s in _run(matrix))

    assert "Only one study here reports cost" in texts


def test_statements_are_deterministic():
    """Recomputation IS the gate: it must reproduce the sentence exactly."""
    matrix = [_study(f"d{i}", [_finding("latency", f"{i}.0s", dataset="HotpotQA")])
              for i in range(1, 6)]

    assert [s["text"] for s in _run(matrix)] == [s["text"] for s in _run(matrix)]


def test_no_statement_is_emitted_without_attributable_rows():
    """A number the reader cannot follow back to studies is not publishable."""
    # Findings whose dimension does not match any row's findings: the synthesis
    # may count something, but nothing here can be attributed.
    statements = derive_statements(
        {"studies_total": 3,
         "dimensions": [{"dimension": "phantom", "studies": 3,
                         "largest_comparable_set": 0, "kind": "quantitative",
                         "state": "moderately_supported", "basis": "b"}]},
        [_study("d1", [_finding("latency", "1.0s")])],
    )

    assert statements == []


def test_an_empty_corpus_produces_no_sentences():
    assert derive_statements({}, []) == []
    assert derive_statements({"studies_total": 0, "dimensions": []}, []) == []


def test_derived_statements_never_generalise_beyond_the_corpus():
    """D may state counts; claims about "the field" are I, and I is not shipped."""
    matrix = [_study(f"d{i}", [_finding("accuracy", "89.0%", dataset=f"S{i}")])
              for i in range(1, 6)]

    texts = " ".join(s["text"] for s in _run(matrix)).lower()

    for forbidden in ("the field", "the literature", "researchers should",
                      "more research is needed", "suggests that", "this implies"):
        assert forbidden not in texts, f"a D sentence generalised: {forbidden!r}"


def test_composition_replaces_the_verified_against_sources_badge():
    comp = composition(verified_claims=38, derived=6)

    assert comp["verified"] == 38 and comp["derived"] == 6
    # Present and zero until I ships, so the header's shape does not change.
    assert comp["inferred"] == 0
    assert "reproducible by recomputation" in comp["note"]


# ── S1: the pooled result ─────────────────────────────────────────────────
#
# `synthesize` has always computed a min/max/median span for every comparable
# bucket, and nothing ever rendered it: the single number a researcher opened
# the report for was calculated, persisted, and thrown away.

def _f(dimension: str, value: str, **ctx) -> dict:
    return _finding(dimension, value, **ctx)


def test_the_pooled_result_is_stated_with_its_range():
    matrix = [
        _study("d1", [_f("accuracy", "87.5%", dataset="HotpotQA", task="multi-hop QA")]),
        _study("d2", [_f("accuracy", "91.0%", dataset="HotpotQA", task="multi-hop QA")]),
        _study("d3", [_f("accuracy", "89.2%", dataset="HotpotQA", task="multi-hop QA")]),
    ]

    pooled = [s for s in _run(matrix) if s["kind"] == "pooled"]

    assert len(pooled) == 1, [s["text"] for s in _run(matrix)]
    text = pooled[0]["text"]
    assert "87.5%" in text and "91%" in text, text
    assert "median 89.2%" in text, text
    assert sorted(pooled[0]["doc_ids"]) == ["d1", "d2", "d3"]


def test_a_pooled_number_always_carries_the_context_that_qualifies_it():
    """Two studies reporting 89.2 are not agreeing unless the context matches."""
    matrix = [
        _study("d1", [_f("accuracy", "88.0%", dataset="HotpotQA", task="multi-hop QA")]),
        _study("d2", [_f("accuracy", "90.0%", dataset="HotpotQA", task="multi-hop QA")]),
    ]

    text = [s for s in _run(matrix) if s["kind"] == "pooled"][0]["text"]

    assert "HotpotQA" in text and "multi-hop QA" in text, text


def test_one_study_is_not_a_pooled_result():
    matrix = [_study("d1", [_f("accuracy", "88.0%", dataset="HotpotQA")]),
              _study("d2", [_f("accuracy", "88.0%", dataset="MuSiQue")])]

    assert [s for s in _run(matrix) if s["kind"] == "pooled"] == []


# ── S2: direction, counted within studies ─────────────────────────────────

def _pair(doc_id: str, dim: str, a: tuple[str, str], b: tuple[str, str],
          dataset: str = "HotpotQA") -> dict:
    """One study that measured TWO systems on the same metric and dataset."""
    return _study(doc_id, [
        _f(dim, a[1], dataset=dataset, model=a[0]),
        _f(dim, b[1], dataset=dataset, model=b[0]),
    ])


def test_direction_counts_within_study_comparisons():
    matrix = [
        _pair("d1", "accuracy", ("GraphRAG", "91.0%"), ("VectorRAG", "84.0%")),
        _pair("d2", "accuracy", ("GraphRAG", "88.0%"), ("VectorRAG", "85.0%")),
        _pair("d3", "accuracy", ("GraphRAG", "80.0%"), ("VectorRAG", "86.0%")),
    ]

    directions = [s for s in _run(matrix) if s["kind"] == "direction"]

    assert len(directions) == 1
    text = directions[0]["text"]
    assert "Of the 3 studies" in text and "2 recorded a higher value for GraphRAG" in text, text
    assert sorted(directions[0]["doc_ids"]) == ["d1", "d2", "d3"]


def test_a_unanimous_direction_says_so():
    matrix = [
        _pair("d1", "accuracy", ("A", "90.0%"), ("B", "80.0%")),
        _pair("d2", "accuracy", ("A", "70.0%"), ("B", "60.0%")),
    ]

    text = [s for s in _run(matrix) if s["kind"] == "direction"][0]["text"]

    assert "In all 2 studies" in text and "A recorded the higher value" in text, text


def test_direction_never_calls_a_system_better():
    """Higher is better for F1 and worse for latency; the matrix says neither.

    Ranking systems by desirability is an interpretation, not arithmetic — an I
    sentence. These may only report which value was larger.
    """
    matrix = [
        _pair("d1", "latency", ("A", "9.0s"), ("B", "2.0s")),
        _pair("d2", "latency", ("A", "8.0s"), ("B", "3.0s")),
    ]

    text = " ".join(s["text"] for s in _run(matrix)).lower()

    for word in ("better", "worse", "outperform", "wins", "superior", "best system"):
        assert word not in text, f"a D sentence made a value judgement: {word!r}"


def test_cross_study_numbers_alone_never_produce_a_direction():
    """Two papers sharing only a benchmark name differ in unrecorded ways.

    A direction requires a comparison the STUDY controlled — otherwise it is a
    coincidence of two numbers, which is exactly the false corroboration the
    normalization layer exists to prevent.
    """
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="GraphRAG")]),
        _study("d2", [_f("accuracy", "84.0%", dataset="HotpotQA", model="VectorRAG")]),
    ]

    assert [s for s in _run(matrix) if s["kind"] == "direction"] == []


def test_a_tie_within_a_study_is_not_a_direction():
    matrix = [
        _pair("d1", "accuracy", ("A", "90.0%"), ("B", "90.0%")),
        _pair("d2", "accuracy", ("A", "90.0%"), ("B", "90.0%")),
    ]

    assert [s for s in _run(matrix) if s["kind"] == "direction"] == []


def test_answer_level_statements_lead_the_corpus_level_ones():
    """The pooled number and the direction are what the reader came for."""
    matrix = [
        _pair("d1", "accuracy", ("A", "91.0%"), ("B", "84.0%")),
        _pair("d2", "accuracy", ("A", "88.0%"), ("B", "85.0%")),
    ]

    kinds = [s["kind"] for s in _run(matrix)]

    assert kinds[0] == "direction", kinds
    assert kinds.index("pooled") < kinds.index("coverage"), kinds


def test_a_pooled_range_never_spans_two_systems():
    """The gap between systems IS the finding — pooling it away destroys it.

    A comparable bucket keys on dimension/metric/dataset/task: enough to say two
    numbers measure the same THING, not enough to say they measure the same
    SUBJECT. Pooling wholesale produced "3 studies measured accuracy on
    HotpotQA: 80.2% to 91%" from a bucket holding both systems — a range
    describing neither. No gate catches it, because every number is real.
    """
    matrix = [
        _pair("d1", "accuracy", ("GraphRAG", "91.0%"), ("VectorRAG", "84.0%")),
        _pair("d2", "accuracy", ("GraphRAG", "88.4%"), ("VectorRAG", "85.1%")),
    ]

    pooled = [s for s in _run(matrix) if s["kind"] == "pooled"]

    assert len(pooled) == 2, [s["text"] for s in pooled]
    by_system = {s["text"].split(",")[1].strip().split(" on ")[0] for s in pooled}
    assert by_system == {"GraphRAG", "VectorRAG"}, by_system
    graph = next(s for s in pooled if "GraphRAG" in s["text"])
    assert "88.4% to 91%" in graph["text"], graph["text"]
    assert "84%" not in graph["text"], "a rival system's number leaked into the span"


def test_two_values_do_not_report_a_median_no_study_measured():
    matrix = [
        _study("d1", [_f("accuracy", "80.0%", dataset="HotpotQA", model="A")]),
        _study("d2", [_f("accuracy", "90.0%", dataset="HotpotQA", model="A")]),
    ]

    text = [s for s in _run(matrix) if s["kind"] == "pooled"][0]["text"]

    assert "spans 80% to 90%" in text, text
    assert "median" not in text, "printed a midpoint no study reported"
