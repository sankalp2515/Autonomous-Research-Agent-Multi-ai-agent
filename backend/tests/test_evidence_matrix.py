"""Phase 1 — the evidence matrix must stay inside the grounding contract.

The matrix is a NEW rendering surface, so it is a new way to leak ungrounded
text into the report. These tests pin the two properties that keep G1/G2 true
for it: a finding that fails the gate never reaches the matrix, and every
finding that does reach it is backed by a persisted Claim + ClaimEvidence row
(which is what makes each cell click-to-source).
"""

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from app.agents import nodes
from app.agents.schemas import StudyFinding, StudyRecord


@dataclass
class _Chunk:
    chunk_id: str
    text: str
    document_title: str = "A Paper"
    section: str = "Results"
    page_start: int = 1
    page_end: int = 2
    abstract_only: bool = False


CHUNK_TEXT = ("GraphRAG improves multi-hop accuracy to 89% versus 63% for "
              "vector approaches, at the cost of higher latency.")


class _FakeSession:
    """Captures rows the node persists; assigns ids like a real flush would."""

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


@pytest.fixture
def patched(monkeypatch):
    session = _FakeSession()

    @asynccontextmanager
    async def fake_scope():
        yield session

    async def fake_retrieve(*_a, **_kw):
        return [_Chunk("c1", CHUNK_TEXT)]

    monkeypatch.setattr(nodes, "session_scope", fake_scope)
    monkeypatch.setattr(nodes, "retrieve", fake_retrieve)
    return session


def _state():
    return {"run_id": "r", "project_id": "p", "llm_calls_used": 0,
            "started_at": time.time(), "coverage_notes": []}


async def test_unverified_findings_never_enter_the_matrix(patched, monkeypatch):
    """A fabricated quote fails quote-match and must be dropped, not rendered."""
    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return StudyRecord(
            frameworks=["GraphRAG"], baselines=["VectorRAG"], datasets=["HotpotQA"],
            findings=[
                # Real: quote is verbatim from CHUNK_TEXT.
                StudyFinding(dimension="multi-hop accuracy",
                             text="GraphRAG reaches 89% multi-hop accuracy.",
                             metric="accuracy", value="89%", chunk_id="c1",
                             quote="improves multi-hop accuracy to 89%"),
                # Fabricated: this sentence appears nowhere in the chunk.
                StudyFinding(dimension="token cost",
                             text="GraphRAG halves token cost.",
                             metric="tokens", value="-50%", chunk_id="c1",
                             quote="GraphRAG halves token cost on every benchmark"),
            ],
        )

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    row = await nodes._extract_one_study(
        _state(), "doc1", "A Paper", 2026, "compare GraphRAG vs RAG", [])

    assert row is not None
    texts = [f["text"] for f in row["findings"]]
    assert "GraphRAG reaches 89% multi-hop accuracy." in texts
    assert "GraphRAG halves token cost." not in texts, (
        "a fabricated quote reached the evidence matrix — the gate is being "
        "bypassed on this surface")


async def test_every_matrix_finding_is_backed_by_a_persisted_claim(patched, monkeypatch):
    """G2: the UI only renders gate-verified Claim rows, so each cell needs one."""
    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return StudyRecord(
            frameworks=["GraphRAG"],
            findings=[StudyFinding(
                dimension="multi-hop accuracy",
                text="GraphRAG reaches 89% multi-hop accuracy.",
                metric="accuracy", value="89%", chunk_id="c1",
                quote="improves multi-hop accuracy to 89%")],
        )

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    row = await nodes._extract_one_study(
        _state(), "doc1", "A Paper", 2026, "compare GraphRAG vs RAG", [])

    claim_ids = [f["claim_id"] for f in row["findings"]]
    assert all(claim_ids), "a matrix cell has no Claim row to resolve"

    persisted = {type(r).__name__ for r in patched.added}
    assert "Claim" in persisted and "ClaimEvidence" in persisted
    # The evidence row must carry the real span offsets the rail highlights.
    ev = next(r for r in patched.added if type(r).__name__ == "ClaimEvidence")
    assert ev.quote_char_end > ev.quote_char_start


async def test_paper_with_no_relevant_content_yields_no_row(patched, monkeypatch):
    """Refusal over fabrication (G4) applies to extraction too."""
    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return StudyRecord(no_relevant_content=True, findings=[])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    row = await nodes._extract_one_study(
        _state(), "doc1", "Off-topic Paper", 2026, "compare GraphRAG vs RAG", [])
    assert row is None


# ── dimension consolidation (Phase 1 fix) ────────────────────────────────
# The first real run produced 'performance', 'accuracy', 'accuracy improvement'
# and 'multi-hop accuracy' as four separate columns, each filled by the one or
# two studies using that phrasing — a wide grid of em-dashes that reads as "no
# evidence" when 56 findings existed.

def _row(doc, dims):
    return {"doc_id": doc, "title": doc, "year": 2026, "frameworks": [],
            "baselines": [], "datasets": [],
            "findings": [{"dimension": d, "text": "t", "metric": "", "value": "",
                          "chunk_id": "c", "quote": "q", "claim_id": "cl",
                          "nli_label": "entailment", "nli_score": 0.9}
                         for d in dims]}


async def test_near_duplicate_dimensions_are_merged(monkeypatch):
    from app.agents.schemas import DimensionAlias, DimensionMap

    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return DimensionMap(
            canonical=["accuracy", "latency"],
            aliases=[DimensionAlias(raw="accuracy improvement", canonical="accuracy"),
                     DimensionAlias(raw="multi-hop accuracy", canonical="accuracy"),
                     DimensionAlias(raw="performance", canonical="accuracy"),
                     DimensionAlias(raw="accuracy", canonical="accuracy"),
                     DimensionAlias(raw="response time", canonical="latency"),
                     DimensionAlias(raw="query latency", canonical="latency"),
                     DimensionAlias(raw="latency", canonical="latency")])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    # 7 distinct labels — above evidence_max_dimensions, so consolidation runs.
    matrix = [_row("d1", ["accuracy improvement", "latency"]),
              _row("d2", ["multi-hop accuracy", "response time"]),
              _row("d3", ["performance", "accuracy", "query latency"])]

    out = await nodes._canonicalize_dimensions(_state(), matrix, "objective")
    dims = {f["dimension"] for r in out for f in r["findings"]}
    assert dims == {"accuracy", "latency"}


async def test_consolidation_never_touches_the_evidence(monkeypatch):
    """It may rename an axis; it may not alter a claim, quote or verdict."""
    from app.agents.schemas import DimensionAlias, DimensionMap

    async def fake_complete_json(_kind, _prompt, _schema, **_kw):
        return DimensionMap(canonical=["accuracy"], aliases=[
            DimensionAlias(raw=d, canonical="accuracy")
            for d in ("a", "b", "c", "d", "e", "f", "g")])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    matrix = [_row("d1", list("abcdefg"))]
    before = [(f["text"], f["quote"], f["chunk_id"], f["nli_score"])
              for f in matrix[0]["findings"]]

    out = await nodes._canonicalize_dimensions(_state(), matrix, "objective")
    after = [(f["text"], f["quote"], f["chunk_id"], f["nli_score"])
             for f in out[0]["findings"]]
    assert before == after


async def test_few_dimensions_skips_the_call(monkeypatch):
    """No consolidation call when the axes are already tidy — it costs budget."""
    called = {"n": 0}

    async def fake_complete_json(*_a, **_kw):
        called["n"] += 1
        raise AssertionError("should not be called")

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)
    matrix = [_row("d1", ["accuracy", "latency"])]
    out = await nodes._canonicalize_dimensions(_state(), matrix, "objective")
    assert called["n"] == 0 and out is matrix
