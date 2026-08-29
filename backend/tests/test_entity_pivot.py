"""S3 — the pivot from study x dimension to SYSTEM x dimension.

The evidence matrix is indexed by study because that is how evidence arrives.
Researchers reason system-first: asked to choose between two systems they hold a
system-indexed table in their head, and a study-indexed matrix makes them
rebuild it by hand.

THE TRAP THIS DESIGN AVOIDS, and what most of this file tests. The obvious pivot
is one grid — systems down the side, dimensions across the top. Its columns
invite exactly the comparison the synthesis layer exists to forbid: "GraphRAG
91%, LightRAG 87%" reads as a ranking even when the numbers are F1 on HotpotQA
and Recall@10 on MuSiQue. No gate catches that, because both numbers are real,
quoted, and correctly attributed to their papers. The fabrication happens in the
LAYOUT.

So the unit is the measurement context, not the grid, and the tests below pin
the consequences: nothing pools across contexts, levels never mix with deltas,
relational labels never become system names, and a table whose systems each come
from a different paper is labelled a juxtaposition rather than a comparison.
"""

from app.agents.normalize import canonical_entity, entity_display
from app.agents.synthesis import synthesize


def _f(dimension: str, value: str, **context) -> dict:
    ctx = {"dataset": "", "task": "", "baseline": "", "model": "", "condition": ""}
    ctx.update(context)
    return {"dimension": dimension, "metric": context.get("metric", dimension),
            "value": value, "text": f"{dimension} {value}",
            "claim_id": f"c-{dimension}-{value}-{context.get('model','')}",
            "chunk_id": "chunk", "quote": "q", "context": ctx}


def _study(doc_id: str, findings: list[dict]) -> dict:
    return {"doc_id": doc_id, "title": f"Study {doc_id}", "year": 2026,
            "findings": findings, "full_text": True}


def _tables(matrix: list[dict]) -> list[dict]:
    return synthesize(matrix)["comparisons"]


def _one(matrix: list[dict]) -> dict:
    tables = _tables(matrix)
    assert len(tables) == 1, [
        (t["metric"], t["dataset"], t["signed"]) for t in tables]
    return tables[0]


# ── entity identity ───────────────────────────────────────────────────────

def test_spelling_variants_of_one_system_merge():
    assert canonical_entity("GraphRAG") == canonical_entity("Graph-RAG")
    assert canonical_entity("GraphRAG (ours)") == canonical_entity("graphrag")
    assert canonical_entity("Llama-3.1-8B") == canonical_entity("Llama 3.1 8B")


def test_similar_but_distinct_models_never_merge():
    """Over-merging fabricates a finding; under-merging only duplicates a row.

    "GPT-4" and "GPT-4o" are one character apart and are different models, which
    is why nothing here is fuzzy — no edit distance, no prefix matching.
    """
    assert canonical_entity("GPT-4") != canonical_entity("GPT-4o")
    assert canonical_entity("Llama-3-8B") != canonical_entity("Llama-3-70B")


def test_relational_labels_are_not_system_names():
    """"ours" means a different system in every paper.

    Accepting it would pool unrelated results into a single row and report the
    total as a cross-study finding.
    """
    for label in ("ours", "our method", "baseline", "proposed", "the model",
                  "n/a", "", "  ", "42"):
        assert canonical_entity(label) == "", label


def test_display_name_is_the_commonest_spelling():
    assert entity_display(["GraphRAG", "graphrag", "GraphRAG", "Graph-RAG"]) == "GraphRAG"


def test_a_spelling_tie_prefers_the_plainest_form():
    """A bare alphabetical tie-break favours hyphens: '-' sorts below letters."""
    assert entity_display(["Graph-RAG", "GraphRAG"]) == "GraphRAG"


# ── the tables ────────────────────────────────────────────────────────────

def test_systems_pivot_into_one_table_per_context():
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="GraphRAG"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="Vector RAG")]),
        _study("d2", [_f("accuracy", "88.4%", dataset="HotpotQA", model="Graph-RAG"),
                      _f("accuracy", "85.1%", dataset="HotpotQA", model="VectorRAG")]),
    ]

    table = _one(matrix)

    assert table["systems"] == 2 and table["studies"] == 2
    rows = {r["key"]: r for r in table["rows"]}
    assert set(rows) == {"graphrag", "vectorrag"}
    assert rows["graphrag"]["studies"] == 2
    assert rows["graphrag"]["min"] == 88.4 and rows["graphrag"]["max"] == 91.0
    # A merged row must show what was merged, so a wrong merge is visible to the
    # reader rather than being a silent join.
    assert rows["graphrag"]["aliases"] == ["Graph-RAG", "GraphRAG"]
    # Which spelling is DISPLAYED on a frequency tie is arbitrary; that it is
    # one the papers actually used is not.
    assert rows["graphrag"]["system"] in rows["graphrag"]["aliases"]


def test_numbers_never_pool_across_measurement_contexts():
    """The whole reason the unit is the context and not a systems x axes grid."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d2", [_f("accuracy", "62.0%", dataset="MuSiQue", model="A"),
                      _f("accuracy", "58.0%", dataset="MuSiQue", model="B")]),
    ]

    tables = _tables(matrix)

    assert len(tables) == 2, "two datasets were fused into one comparison"
    for t in tables:
        values = [v for r in t["rows"] for v in r["values"]]
        assert max(values) - min(values) < 30, (
            f"a table pooled HotpotQA and MuSiQue numbers: {values}")


def test_levels_and_deltas_are_never_shown_in_one_table():
    """"89.2%" is a score and "+3.1%" is a change in one; they share a unit."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d2", [_f("accuracy", "+3.1%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "+5.4%", dataset="HotpotQA", model="B")]),
    ]

    tables = _tables(matrix)

    assert {t["signed"] for t in tables} == {False, True}
    for t in tables:
        values = [v for r in t["rows"] for v in r["values"]]
        assert (max(values) < 10) == t["signed"], (t["signed"], values)


def test_a_table_needs_at_least_two_systems():
    """One system is a measurement, not a comparison."""
    matrix = [_study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A")]),
              _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="A")])]

    assert _tables(matrix) == []


def test_a_dataset_name_in_the_model_field_is_not_a_system():
    """An extractor that wrote the benchmark into `model` told us nothing."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="HotpotQA"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="GraphRAG"),
                      _f("accuracy", "80.0%", dataset="HotpotQA", model="Vector RAG")]),
    ]

    table = _one(matrix)

    assert {r["system"] for r in table["rows"]} == {"GraphRAG", "Vector RAG"}


def test_unattributed_numbers_are_excluded_not_bucketed_together():
    """Two numbers with no system are not two measurements of one system."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="ours"),
                      _f("accuracy", "70.0%", dataset="HotpotQA", model="baseline")]),
        _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="ours"),
                      _f("accuracy", "60.0%", dataset="HotpotQA", model="baseline")]),
    ]

    assert _tables(matrix) == [], "relational labels were treated as systems"


# ── comparison vs juxtaposition ───────────────────────────────────────────

def test_a_table_reports_how_many_studies_compared_the_systems_directly():
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "85.0%", dataset="HotpotQA", model="B")]),
    ]

    table = _one(matrix)

    assert table["within_study"] == 2


def test_systems_from_different_papers_are_marked_as_juxtaposed():
    """A column of numbers that no study ever put side by side.

    The table shape is identical to a real comparison and the reader cannot tell
    the difference by looking — so the count is carried rather than inferred.
    """
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A")]),
        _study("d2", [_f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
    ]

    table = _one(matrix)

    assert table["systems"] == 2
    assert table["within_study"] == 0


def test_strongest_comparisons_are_ordered_first():
    matrix = [
        # juxtaposition on MuSiQue
        _study("d1", [_f("accuracy", "50.0%", dataset="MuSiQue", model="A")]),
        _study("d2", [_f("accuracy", "55.0%", dataset="MuSiQue", model="B")]),
        # controlled comparison on HotpotQA
        _study("d3", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d4", [_f("accuracy", "88.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "85.0%", dataset="HotpotQA", model="B")]),
    ]

    tables = _tables(matrix)

    assert tables[0]["dataset"] == "HotpotQA"
    assert tables[0]["within_study"] == 2
    assert tables[-1]["within_study"] == 0


def test_rows_are_not_ordered_by_value():
    """Ordering by value ranks the systems, and which end is good is unknown.

    Higher is better for F1 and worse for latency; nothing in the matrix records
    which way an axis points, so a value-ordered table would smuggle in an
    interpretation the contract reserves for I sentences.
    """
    matrix = [
        _study("d1", [_f("latency", "9.0s", dataset="HotpotQA", model="Slow"),
                      _f("latency", "1.0s", dataset="HotpotQA", model="Fast")]),
        _study("d2", [_f("latency", "8.0s", dataset="HotpotQA", model="Slow"),
                      _f("latency", "1.5s", dataset="HotpotQA", model="Fast")]),
    ]

    rows = _one(matrix)["rows"]

    # Equal study counts -> alphabetical, NOT best-first or worst-first.
    assert [r["system"] for r in rows] == ["Fast", "Slow"]


def test_every_row_can_be_traced_to_its_claims():
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
    ]

    for row in _one(matrix)["rows"]:
        assert row["claim_ids"], f"{row['system']} has no click-through provenance"
        assert row["doc_ids"]


def test_the_pivot_is_deterministic():
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "85.0%", dataset="HotpotQA", model="B")]),
    ]

    first, second = _tables(matrix), _tables(matrix)

    assert first == second


# ── entity coverage ───────────────────────────────────────────────────────

def test_entity_coverage_accounts_for_systems_no_table_can_show():
    """A system measured once on one axis appears in no comparison.

    Its absence from the tables must not read as absence from the corpus.
    """
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="B")]),
        _study("d2", [_f("cost", "5 USD", dataset="HotpotQA", model="Lonely")]),
    ]

    coverage = {e["system"]: e for e in synthesize(matrix)["entity_coverage"]}

    assert "Lonely" in coverage
    assert coverage["Lonely"]["studies"] == 1
    assert coverage["Lonely"]["dimensions"][0]["dimension"] == "cost"


def test_entity_coverage_counts_studies_not_findings():
    """One paper reporting a system three times is one study, not three."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="A"),
                      _f("accuracy", "88.0%", dataset="MuSiQue", model="A"),
                      _f("accuracy", "70.0%", dataset="2WikiMQA", model="A")]),
    ]

    entity = synthesize(matrix)["entity_coverage"][0]

    assert entity["studies"] == 1
    assert entity["dimensions"][0]["findings"] == 3
    assert entity["dimensions"][0]["studies"] == 1


# ── S2 shares the identity rules ──────────────────────────────────────────

def test_directions_use_canonical_identity_too():
    """S2 pairing on raw text would make "GraphRAG" and "Graph-RAG" rivals."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="GraphRAG"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="Vector RAG")]),
        _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="Graph-RAG"),
                      _f("accuracy", "85.0%", dataset="HotpotQA", model="VectorRAG")]),
    ]

    dims = synthesize(matrix)["dimensions"]
    directions = [d for dim in dims for d in dim["directions"]]

    assert len(directions) == 1
    assert directions[0]["studies"] == 2
    # Canonical keys are what identity is decided on; the displayed spelling is
    # whichever the papers used most.
    assert {directions[0]["key_a"], directions[0]["key_b"]} == {
        "graphrag", "vectorrag"}


def test_directions_never_pair_relational_labels():
    """"ours beat baseline in 2 of 2 studies" pools two unrelated comparisons."""
    matrix = [
        _study("d1", [_f("accuracy", "91.0%", dataset="HotpotQA", model="ours"),
                      _f("accuracy", "84.0%", dataset="HotpotQA", model="baseline")]),
        _study("d2", [_f("accuracy", "88.0%", dataset="HotpotQA", model="ours"),
                      _f("accuracy", "85.0%", dataset="HotpotQA", model="baseline")]),
    ]

    dims = synthesize(matrix)["dimensions"]

    assert [d for dim in dims for d in dim["directions"]] == []
