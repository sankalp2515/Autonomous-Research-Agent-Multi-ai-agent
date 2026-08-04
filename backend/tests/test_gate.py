"""Gate behavior tests with NLI disabled (the deterministic layers).
NLI-dependent behavior is covered in evals where the model is available.
"""

import pytest

from app.core.config import get_settings
from app.verification.gate import ClaimInput, verify_claim, verify_claims


@pytest.fixture(autouse=True)
def disable_nli(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ml_nli_enabled", False)


CHUNK_TEXT = (
    "Retrieval-augmented generation reduces hallucination rates by grounding "
    "outputs in retrieved passages. In our study, RAG reduced factual errors "
    "by 37% compared to closed-book generation."
)


async def test_verified_claim_passes():
    claim = ClaimInput(
        text="RAG reduced factual errors by 37% versus closed-book generation.",
        chunk_id="c1",
        quote="RAG reduced factual errors by 37% compared to closed-book generation",
    )
    result = await verify_claim(claim, CHUNK_TEXT)
    assert result.verified and result.reason == "ok"
    assert result.evidence.quote_match.char_start >= 0


async def test_missing_chunk_fails():
    claim = ClaimInput("any claim", "ghost-chunk", "any quote whatsoever here")
    result = await verify_claim(claim, None)
    assert not result.verified and result.reason == "missing_chunk"


async def test_fabricated_quote_fails():
    claim = ClaimInput(
        text="RAG eliminates hallucinations entirely.",
        chunk_id="c1",
        quote="RAG eliminates one hundred percent of hallucinations in all settings",
    )
    result = await verify_claim(claim, CHUNK_TEXT)
    assert not result.verified and result.reason == "quote_mismatch"


async def test_batch_report_counts():
    claims = [
        ClaimInput("ok claim",
                   "c1", "reduces hallucination rates by grounding outputs"),
        ClaimInput("bad claim", "c1", "this quote was never in the source text at all"),
        ClaimInput("orphan claim", "missing", "reduces hallucination rates"),
    ]
    report = await verify_claims(claims, {"c1": CHUNK_TEXT})
    assert report.verified_count == 1
    assert report.failed == [1, 2]
    assert 0.3 < report.support_rate < 0.4


# ── Over-specification guard ─────────────────────────────────────────────

from app.verification.gate import _extract_entities, unsupported_entities  # noqa: E402


def test_extract_entities_splits_on_possessive():
    # "IBM's AI Fairness 360" must yield IBM + "AI Fairness", not a merged phrase.
    ents = _extract_entities("IBM's AI Fairness 360 provides bias metrics.")
    assert "IBM" in ents
    assert "AI Fairness" in ents
    assert not any("IBM AI" in e for e in ents)


def test_extract_entities_ignores_sentence_start_and_ubiquitous():
    # Leading "The", lone Title-case words, and ubiquitous acronyms are noise.
    ents = _extract_entities("Measurement bias affects the EU and AI systems.")
    assert ents == []


def test_unsupported_named_act_flagged():
    chunk = ("The framework addresses regulatory constraints in machine learning "
             "without naming any specific statute.")
    missing = unsupported_entities(
        "The EU's Artificial Intelligence Act mandates bias monitoring.", chunk)
    assert missing == ["Artificial Intelligence Act"]


async def test_gate_fails_claim_naming_absent_law():
    # The real InfoGram/EU-AI-Act case: quote matches a generic sentence, but
    # the claim names a law the source never mentions -> gate must reject it.
    chunk = ("The framework addresses regulatory constraints in machine learning "
             "without naming any specific statute.")
    claim = ClaimInput(
        text="The EU's Artificial Intelligence Act mandates bias monitoring for high-risk systems.",
        chunk_id="c1",
        quote="regulatory constraints in machine learning",
    )
    result = await verify_claim(claim, chunk)
    assert not result.verified and result.reason == "unsupported_entity"


async def test_gate_passes_when_entity_present():
    chunk = ("IBM's AI Fairness 360 toolkit provides metrics to detect and "
             "mitigate dataset bias.")
    claim = ClaimInput(
        text="IBM's AI Fairness 360 provides metrics to detect and mitigate bias.",
        chunk_id="c1",
        quote="provides metrics to detect and mitigate",
    )
    result = await verify_claim(claim, chunk)
    assert result.verified


async def test_gate_accepts_acronym_expansion():
    # Claim spells out a name the source gives as an acronym -> still supported.
    chunk = "The GDPR requires data controllers to document processing activities."
    claim = ClaimInput(
        text="The General Data Protection Regulation requires controllers to document processing.",
        chunk_id="c1",
        quote="to document processing activities",
    )
    result = await verify_claim(claim, chunk)
    assert result.verified


async def test_entity_check_can_be_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "gate_entity_check_enabled", False)
    chunk = "The framework addresses regulatory constraints in machine learning."
    claim = ClaimInput(
        text="The EU's Artificial Intelligence Act mandates bias monitoring.",
        chunk_id="c1",
        quote="regulatory constraints in machine learning",
    )
    result = await verify_claim(claim, chunk)
    assert result.verified  # guard off -> passes deterministic layers
