"""The verification appendix and the published protocol.

Two properties are pinned here, both of which the report layout depends on and
neither of which existed before:

1. A REFUSED claim survives. It used to be dropped, leaving only a count — and
   a count cannot be judged. Every refusal must reach the report carrying the
   source span it was checked against, so a reader can see what the gate caught
   AND where it was wrong.

2. The PUBLISHED protocol is the APPLIED protocol. The screening criteria and
   the per-column extraction instructions are printed in the report, so they
   must survive `normalized()` unchanged. If normalization silently dropped
   them (it did, until this was pinned), the report would print an empty method
   section while the screen went on using a different, invisible prompt — a
   review that cannot be reproduced from what it publishes.
"""

from app.agents.nodes import _MAX_REFUSALS, _record_refusals, _refusal_span
from app.agents.schemas import (
    EvidenceDimension, ResearchEvidenceSchema, ScreeningCriterion,
)
from app.verification.gate import EvidenceResult, GateResult
from app.verification.quote_match import QuoteMatch


class _Claim:
    def __init__(self, text, chunk_id, quote):
        self.text, self.chunk_id, self.quote = text, chunk_id, quote


def _ok(chunk_id="c1", quote="q"):
    return GateResult(True, "ok", EvidenceResult(
        chunk_id, quote, QuoteMatch(True, "exact", 1.0, 0, 1), "entailment", 0.9))


def _fail(reason, label="neutral", score=0.97, chunk_id="c1", quote="q"):
    return GateResult(False, reason, EvidenceResult(
        chunk_id, quote, QuoteMatch(False, "none", 0.0, -1, -1), label, score))


# ── 1. refusals survive ──────────────────────────────────────────────────

def test_refused_claim_is_kept_with_its_source_span():
    source = ("Experimental results demonstrate that the framework converges "
              "23% faster than FedOPT on the benchmark suite, and lowers energy "
              "consumption by 35% relative to the baseline models.")
    state = {}
    claims = [_Claim("The framework converges 23% faster.", "c1", "converges 23% faster")]
    _record_refusals(state, claims, [_fail("nli_weak")], {"c1": source},
                     stage="drafting", section="Efficiency")

    (row,) = state["refused_claims"]
    assert row["reason"] == "nli_weak"
    assert row["stage"] == "drafting"
    assert row["section"] == "Efficiency"
    assert row["nli_label"] == "neutral"
    assert row["nli_score"] == 0.97
    # The span must be the real passage, centred on the quote — that is what
    # makes the refusal legible next to the claim.
    assert "converges 23% faster" in row["source_span"]
    assert state["refusal_reasons"] == {"nli_weak": 1}


def test_verified_claims_are_not_recorded_as_refusals():
    state = {}
    claims = [_Claim("a", "c1", "q"), _Claim("b", "c1", "q")]
    _record_refusals(state, claims, [_ok(), _fail("quote_mismatch")],
                     {"c1": "some source text about q here"}, stage="extraction")
    assert len(state["refused_claims"]) == 1
    assert state["refused_claims"][0]["text"] == "b"


def test_refusal_tally_is_complete_even_when_the_list_is_capped():
    """The list is bounded so a pathological run cannot grow the checkpoint
    without limit — but the COUNT must stay true, or the appendix would
    understate how much the gate rejected."""
    state = {}
    n = _MAX_REFUSALS + 25
    claims = [_Claim(f"claim {i}", "c1", "q") for i in range(n)]
    results = [_fail("quote_mismatch") for _ in range(n)]
    _record_refusals(state, claims, results, {"c1": "src"}, stage="drafting")

    assert len(state["refused_claims"]) == _MAX_REFUSALS      # bounded
    assert state["refusal_reasons"]["quote_mismatch"] == n     # but honest


def test_refusal_span_falls_back_to_the_chunk_head_when_the_quote_is_absent():
    """A quote that was fabricated outright cannot be located. We show the head
    of the real passage rather than implying a span we did not find."""
    span = _refusal_span("The paper reports no efficiency analysis at all.",
                         "achieves 94.2% accuracy on HotpotQA")
    assert span.startswith("The paper reports no efficiency")
    assert "94.2" not in span


def test_refusal_span_is_empty_for_a_missing_chunk():
    assert _refusal_span("", "anything") == ""


# ── 2. the published protocol is the applied protocol ────────────────────

def test_screening_criteria_survive_normalization():
    schema = ResearchEvidenceSchema(
        required_dimensions=[EvidenceDimension(name="latency")],
        screening_criteria=[
            ScreeningCriterion(name="Direct Comparison",
                               question="Does the study evaluate GraphRAG against a RAG baseline?"),
            ScreeningCriterion(name="Quantitative Evidence",
                               question="Does it report numbers?"),
        ],
    ).normalized()

    assert [c.name for c in schema.screening_criteria] == [
        "Direct Comparison", "Quantitative Evidence"]
    # Published verbatim: case is preserved, unlike the retrieval vocabulary.
    assert schema.screening_criteria[0].name == "Direct Comparison"
    assert "GraphRAG" in schema.screening_criteria[0].question


def test_duplicate_criteria_are_collapsed_case_insensitively():
    schema = ResearchEvidenceSchema(
        required_dimensions=[EvidenceDimension(name="latency")],
        screening_criteria=[
            ScreeningCriterion(name="Direct Comparison", question="a"),
            ScreeningCriterion(name="direct comparison", question="b"),
        ],
    ).normalized()
    assert len(schema.screening_criteria) == 1


def test_extraction_instruction_survives_normalization():
    """Dropped by `_dim()` before this was pinned, which would have printed an
    empty 'Data extraction' section while extraction carried on regardless."""
    schema = ResearchEvidenceSchema(
        required_dimensions=[EvidenceDimension(
            name="Multi-Hop Accuracy",
            extraction_instruction="Extract all accuracy comparisons,\n  including "
                                   "the metric and the dataset.",
        )],
    ).normalized()

    dim = schema.required_dimensions[0]
    assert dim.name == "multi-hop accuracy"          # retrieval vocabulary: lowered
    # Reader-facing prose: whitespace collapsed, case and wording untouched.
    assert dim.extraction_instruction == (
        "Extract all accuracy comparisons, including the metric and the dataset.")


def test_schema_normalization_is_still_deterministic_with_the_new_fields():
    """Two runs of one question must produce the same schema, or nothing
    downstream is comparable between them."""
    def build():
        return ResearchEvidenceSchema(
            research_type="comparison",
            entities=["GraphRAG", "RAG"],
            required_dimensions=[
                EvidenceDimension(name="latency", extraction_instruction="Extract latency."),
                EvidenceDimension(name="accuracy", extraction_instruction="Extract accuracy."),
            ],
            screening_criteria=[ScreeningCriterion(name="Direct Comparison", question="q")],
        ).normalized()

    assert build().model_dump() == build().model_dump()
