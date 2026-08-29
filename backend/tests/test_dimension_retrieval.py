"""P0-B — the retrieval bottleneck that emptied half the evidence matrix.

REGRESSION UNDER TEST. Per-paper extraction used to run ONE query (the run
objective) against a ~63-chunk paper and keep 8 chunks. Measured on a real run:
100 study x dimension cells, 38 filled, and ~31 of the empty ones were empty
even though the paper contained the evidence — e.g. "Comparative Analysis of
Neural Retriever-Reranker" had 4 latency-bearing chunks and a blank latency
cell; "Engineering the RAG Stack" had 16 and a blank latency cell.

The fixtures below reproduce that shape: a paper that is mostly about accuracy,
whose latency and cost numbers sit far down the document. The generic-objective
ranking must miss them (that IS the bug) and dimension-directed retrieval must
find them.
"""

from dataclasses import dataclass

import pytest

from app.retrieval.dimension import (
    DimensionSpec, _evidence_prior, build_dimension_queries,
)


@dataclass
class _Chunk:
    id: str
    text: str
    section: str = ""
    document_id: str = "doc1"
    page_start: int = 1
    page_end: int = 1
    ordinal: int = 0


# A paper shaped like the real ones: accuracy prose everywhere, the efficiency
# numbers in one table late in the document.
def _paper() -> list[_Chunk]:
    chunks: list[_Chunk] = []
    for i in range(40):
        chunks.append(_Chunk(
            id=f"c{i}", ordinal=i, section="Introduction" if i < 4 else "Results",
            text=("GraphRAG improves multi-hop accuracy over standard RAG "
                  "retrieval augmented generation on question answering "
                  f"benchmarks, with accuracy gains reported in setting {i}."),
        ))
    chunks.append(_Chunk(
        id="c_lat", ordinal=41, section="Efficiency Analysis",
        text=("| system | query time | \n| GraphRAG | 9.03 s |\n| VectorRAG | "
              "1.20 s |\nEnd-to-end response time was measured at 9.03 s for "
              "the graph pipeline against 1.20 s for the vector baseline."),
    ))
    chunks.append(_Chunk(
        id="c_tok", ordinal=42, section="Cost Analysis",
        text=("Indexing consumed 1.4M tokens at an estimated 12.50 USD per "
              "corpus build, versus 0.2M tokens for the vector baseline."),
    ))
    return chunks


LATENCY = DimensionSpec(
    name="retrieval latency", kind="quantitative",
    synonyms=["response time", "query time", "inference time", "throughput"],
    metrics=["ms", "s", "qps"], location_hints=["efficiency", "results"],
)
TOKENS = DimensionSpec(
    name="token usage", kind="quantitative",
    synonyms=["token cost", "tokens consumed", "compute cost"],
    metrics=["tokens", "usd"], location_hints=["cost analysis"],
)
ACCURACY = DimensionSpec(
    name="multi-hop accuracy", kind="quantitative",
    synonyms=["accuracy", "f1", "exact match"], metrics=["%", "f1"],
    location_hints=["results"],
)


def _bm25_top(chunks: list[_Chunk], query: str, k: int) -> list[str]:
    """The OLD behaviour, reduced to its essence: one query, top-k, no aiming."""
    import re

    from rank_bm25 import BM25Okapi
    tok = lambda t: re.findall(r"[a-z0-9]+", t.lower())  # noqa: E731
    bm25 = BM25Okapi([tok(c.section + " " + c.text) for c in chunks])
    scores = bm25.get_scores(tok(query))
    return [c.id for _, c in sorted(zip(scores, chunks),
                                    key=lambda t: (t[0], t[1].id), reverse=True)][:k]


def test_the_generic_objective_query_misses_the_efficiency_evidence():
    """Pins the BUG itself, so a future refactor can't quietly reintroduce it."""
    top8 = _bm25_top(_paper(), "compare GraphRAG vs standard RAG", 8)
    assert "c_lat" not in top8 and "c_tok" not in top8, (
        "fixture no longer reproduces the failure the rework exists to fix")


def test_dimension_queries_carry_the_papers_vocabulary():
    qs = build_dimension_queries(LATENCY, ["graphrag", "vectorrag"], "compare X")
    joined = " ".join(q.text for q in qs).lower()
    # The axis name alone is not enough — a paper that only says "query time"
    # and "s" must still be reachable.
    for term in ("response time", "query time", "ms", "qps", "graphrag"):
        assert term in joined, f"{term!r} missing from the retrieval vocabulary"
    # Deterministic: reproducibility of a report depends on it.
    assert qs == build_dimension_queries(LATENCY, ["vectorrag", "graphrag"], "compare X")
    # The generic objective angle exists but must never dominate the axis.
    by_purpose = {q.purpose: q.weight for q in qs}
    assert by_purpose["objective"] < by_purpose["terms"]


def test_dimension_directed_ranking_surfaces_the_missed_evidence():
    """The recall fix: each axis searched in its own words finds its own page."""
    chunks = _paper()
    lat_top = _bm25_top(chunks, build_dimension_queries(LATENCY, [])[0].text, 5)
    tok_top = _bm25_top(chunks, build_dimension_queries(TOKENS, [])[0].text, 5)
    assert "c_lat" in lat_top, "latency evidence still unreachable"
    assert "c_tok" in tok_top, "token-cost evidence still unreachable"


def test_quantitative_axes_prefer_passages_that_carry_numbers():
    """A passage that says the word 'latency' is not evidence about latency;
    a passage that says '9.03 s' is."""
    chunks = {c.id: c for c in _paper()}
    with_number = _evidence_prior(LATENCY, chunks["c_lat"])
    prose_only = _evidence_prior(LATENCY, chunks["c5"])
    assert with_number > prose_only


def test_section_hints_count_as_evidence_of_location():
    chunks = {c.id: c for c in _paper()}
    assert _evidence_prior(TOKENS, chunks["c_tok"]) > _evidence_prior(TOKENS, chunks["c0"])


def test_qualitative_axes_do_not_demand_numbers():
    """A limitations axis must not be biased toward whatever page has digits."""
    lim = DimensionSpec(name="limitation", kind="qualitative",
                        synonyms=["limitation", "future work"],
                        location_hints=["limitations"])
    chunks = {c.id: c for c in _paper()}
    assert _evidence_prior(lim, chunks["c_lat"]) < 0.5


async def test_adaptive_allocation_never_lets_one_axis_starve_the_others(monkeypatch):
    """The per-paper window is shared round-robin across axes.

    With a flat cut, the axis that matched hardest (accuracy, on this corpus)
    would consume the whole window and latency/cost would get nothing — which is
    a slower way of reproducing the original bug.
    """
    import app.retrieval.dimension as dim_mod

    chunks = _paper()

    async def no_embed(_texts):
        raise RuntimeError("no local models in unit tests")

    async def fake_load(_session, _project, _doc):
        return chunks, "A Paper", False

    monkeypatch.setattr(dim_mod, "embed_texts", no_embed)
    monkeypatch.setattr(dim_mod, "_load_document_chunks", fake_load)

    out, coverage = await dim_mod.retrieve_by_dimension(
        None, "p", "doc1", [ACCURACY, LATENCY, TOKENS],
        entities=["graphrag"], objective="compare GraphRAG vs standard RAG",
        per_dimension_k=4, max_chunks=12, use_rerank=False,
    )
    ids = {c.chunk_id for c in out}
    assert "c_lat" in ids and "c_tok" in ids, (
        "an axis was starved out of the paper's evidence window")
    assert len(out) <= 12
    # Coverage is recorded per axis — it is what later licenses (or refuses) a
    # 'not reported' verdict.
    assert coverage["retrieval latency"].examined > 0
    assert coverage["retrieval latency"].queries


async def test_missing_document_yields_no_chunks(monkeypatch):
    import app.retrieval.dimension as dim_mod

    async def fake_load(_s, _p, _d):
        return [], "", False

    monkeypatch.setattr(dim_mod, "_load_document_chunks", fake_load)
    out, cov = await dim_mod.retrieve_by_dimension(None, "p", "gone", [LATENCY])
    assert out == [] and cov == {}


@pytest.mark.parametrize("full_text,queries,examined,expected", [
    (True, 3, 10, True),    # full text, real search -> silence is informative
    (False, 3, 10, False),  # abstract only -> we never had the results at all
    (True, 1, 10, False),   # one query -> we barely asked
    (True, 3, 1, False),    # nothing to read -> nothing to conclude
])
def test_absence_needs_evidence_of_search(full_text, queries, examined, expected):
    """The epistemic hinge: 'not reported' is only licensed by real coverage."""
    from app.retrieval.dimension import DimensionHits, coverage_is_sufficient
    hits = DimensionHits("retrieval latency", ["q"] * queries, [], examined, 0.0)
    assert coverage_is_sufficient(hits, full_text=full_text) is expected
