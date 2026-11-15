"""Compare must not publish OUR failure as a fact about the papers.

Two bugs shipped together here, and the second hid the first.

**The addressing bug.** `_format_sources` names each passage by `_source_id` (a
content hash); `compare.py` keyed its gate lookup by the ROW id. Every cell in
every comparison failed gate layer 1 as `missing_chunk` — the same bug that had
already shipped in `grounded.py`.

**And the UI could not tell you.** A failed cell returned `None`, and `None`
rendered as "— not addressed". So a systemic failure of ours displayed as a
confident finding: none of these five papers addresses any of these four
dimensions. That is the `not_reported` vs `extraction_uncertain` error the
evidence matrix's cell states exist to prevent, in a surface that had no cell
states at all.

These tests pin the addressing AND pin that each of the four ways a cell can end
up empty stays distinguishable — because the second is what makes a recurrence
visible instead of silent.
"""

from dataclasses import dataclass

import pytest

from app.agents import nodes
from app.agents.schemas import DraftClaim
from app.services import compare
from app.services.compare import CellDraft
from app.verification.gate import EvidenceResult, GateReport, GateResult
from app.verification.quote_match import QuoteMatch

CHUNK_TEXT = ("GraphRAG reaches 89.2 F1 on HotpotQA against 63.4 for the vector "
              "baseline, evaluated over three random seeds.")
QUOTE = "89.2 F1 on HotpotQA"
SOURCE_ID = nodes._source_id(CHUNK_TEXT)


@dataclass
class _Chunk:
    chunk_id: str = "real-row-id-7"
    document_id: str = "doc1"
    document_title: str = "GraphRAG at scale"
    section: str = "Results"
    page_start: int = 9
    page_end: int = 10
    text: str = CHUNK_TEXT
    score: float = 0.9
    abstract_only: bool = False
    source_type: str = "paper"


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


def _wire(monkeypatch, *, chunks=None, draft=None, gate=None):
    async def fake_retrieve(*_a, **_kw):
        return [_Chunk()] if chunks is None else chunks

    async def fake_complete_json(*_a, **_kw):
        if draft is not None:
            return draft
        return CellDraft(claim=DraftClaim(
            text="GraphRAG reaches 89.2 F1 on HotpotQA.",
            chunk_id=SOURCE_ID, quote=QUOTE))

    captured: dict = {}

    async def fake_verify(claims, chunk_lookup):
        captured["lookup_keys"] = set(chunk_lookup)
        captured["cited"] = claims[0].chunk_id
        if gate is not None:
            return gate
        # Behave like the real gate: an id the lookup does not know fails.
        report = GateReport()
        if claims[0].chunk_id not in chunk_lookup:
            report.results = [GateResult(False, "missing_chunk")]
        else:
            ev = EvidenceResult(claims[0].chunk_id, QUOTE,
                                QuoteMatch(True, "exact", 1.0, 0, len(QUOTE)),
                                "entailment", 0.93)
            report.results = [GateResult(True, "ok", ev)]
        return report

    monkeypatch.setattr(compare, "retrieve", fake_retrieve)
    monkeypatch.setattr(compare, "complete_json", fake_complete_json)
    monkeypatch.setattr(compare, "verify_claims", fake_verify)
    return captured


# ── the addressing bug ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_lookup_is_keyed_the_way_the_prompt_names_passages(monkeypatch):
    """THE REGRESSION. Keyed by row id, every cell died as `missing_chunk`."""
    session = _FakeSession()
    captured = _wire(monkeypatch)

    cell = await compare._draft_cell(session, "p1", "doc1", "Key result")

    assert captured["cited"] == SOURCE_ID
    assert SOURCE_ID in captured["lookup_keys"], (
        "the gate was keyed by row id while the prompt names passages by "
        "content hash — every cell fails layer 1 and no comparison can fill")
    assert cell["verified"] is True
    assert cell["state"] == compare.CELL_REPORTED


@pytest.mark.asyncio
async def test_persisted_evidence_points_at_a_real_row(monkeypatch):
    """The content hash addresses the PROMPT. What is stored must be a row this
    project owns, or the cell is not click-to-source."""
    session = _FakeSession()
    _wire(monkeypatch)

    cell = await compare._draft_cell(session, "p1", "doc1", "Key result")

    assert cell["chunk_id"] == "real-row-id-7"
    assert cell["page"] == 9
    evidence = [r for r in session.added if type(r).__name__ == "ClaimEvidence"]
    assert evidence and evidence[0].chunk_id == "real-row-id-7"


# ── the four ways a cell ends up empty ───────────────────────────────────

@pytest.mark.asyncio
async def test_only_the_model_reading_and_finding_nothing_is_about_the_paper(monkeypatch):
    session = _FakeSession()
    _wire(monkeypatch, draft=CellDraft(claim=None))

    cell = await compare._draft_cell(session, "p1", "doc1", "Latency")

    assert cell["verified"] is False
    assert cell["state"] == compare.CELL_NOT_ADDRESSED


@pytest.mark.asyncio
async def test_no_retrieved_passages_is_our_limitation_not_the_papers(monkeypatch):
    session = _FakeSession()
    _wire(monkeypatch, chunks=[])

    cell = await compare._draft_cell(session, "p1", "doc1", "Latency")

    assert cell["state"] == compare.CELL_NO_PASSAGES
    assert cell["state"] != compare.CELL_NOT_ADDRESSED
    assert cell["reason"]


@pytest.mark.asyncio
async def test_a_gate_rejection_is_our_limitation_not_the_papers(monkeypatch):
    """THE ONE THAT MATTERS. This is the state the addressing bug produced, and
    it must never again be indistinguishable from 'the paper is silent'."""
    session = _FakeSession()
    failed = GateReport()
    failed.results = [GateResult(False, "missing_chunk")]
    _wire(monkeypatch, gate=failed)

    cell = await compare._draft_cell(session, "p1", "doc1", "Key result")

    assert cell["state"] == compare.CELL_UNVERIFIED
    assert cell["state"] != compare.CELL_NOT_ADDRESSED
    assert "missing_chunk" in cell["reason"]
    # A rejected claim is never persisted.
    assert not [r for r in session.added if type(r).__name__ == "Claim"]


@pytest.mark.asyncio
async def test_every_empty_cell_carries_a_state(monkeypatch):
    """An empty cell with no state renders as the neutral 'not established'.
    One with no state field at all would fall back to the old lie."""
    session = _FakeSession()
    for kwargs in ({"chunks": []}, {"draft": CellDraft(claim=None)}):
        _wire(monkeypatch, **kwargs)
        cell = await compare._draft_cell(session, "p1", "doc1", "Latency")
        assert cell.get("state"), "an empty cell must say why it is empty"
        assert cell["verified"] is False


def test_the_states_are_distinct_and_only_one_is_about_the_paper():
    ours = {compare.CELL_NO_PASSAGES, compare.CELL_UNVERIFIED, compare.CELL_FAILED}
    assert compare.CELL_NOT_ADDRESSED not in ours
    assert compare.CELL_REPORTED not in ours
    assert len(ours) == 3
