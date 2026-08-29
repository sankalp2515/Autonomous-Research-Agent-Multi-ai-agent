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


# ── Layer 3: NLI entailment branch (model mocked; no torch needed) ───────────
# These exercise the decision logic the real model feeds, without loading it —
# previously this branch was only touched in evals "where the model is
# available", leaving the gate's truth decision itself untested in unit CI.

import app.verification.gate as gate  # noqa: E402

# A claim that clears layers 1-2.5 (quote present, no over-specified entity) so
# execution always reaches the NLI layer under test.
_NLI_CLAIM = ClaimInput(
    text="It reduced factual errors by 37% versus closed-book generation.",
    chunk_id="c1",
    quote="reduced factual errors by 37% compared to closed-book generation",
)


def _mock_nli(monkeypatch, label: str, score: float):
    """Turn the NLI layer ON and pin its verdict for both the single and batched
    paths. Patches the names bound INTO the gate module (it imports them by
    value), which is what the gate actually calls."""
    monkeypatch.setattr(gate, "nli_available", lambda: True)

    async def _single(premise, hypothesis):
        return (label, score)

    async def _batch(pairs):
        return [(label, score) for _ in pairs]

    monkeypatch.setattr(gate, "nli_entailment", _single)
    monkeypatch.setattr(gate, "nli_entailment_batch", _batch)


async def test_nli_entailment_passes(monkeypatch):
    _mock_nli(monkeypatch, "entailment", 0.95)
    result = await verify_claim(_NLI_CLAIM, CHUNK_TEXT)
    assert result.verified and result.reason == "ok"
    assert result.evidence.nli_label == "entailment"


async def test_nli_contradiction_fails(monkeypatch):
    _mock_nli(monkeypatch, "contradiction", 0.90)
    result = await verify_claim(_NLI_CLAIM, CHUNK_TEXT)
    assert not result.verified and result.reason == "nli_contradiction"


async def test_nli_strong_neutral_fails_as_out_of_context(monkeypatch):
    # Quote matches, but the chunk says nothing ABOUT the claim (strong neutral):
    # out-of-context quoting must be rejected.
    _mock_nli(monkeypatch, "neutral", 0.90)
    result = await verify_claim(_NLI_CLAIM, CHUNK_TEXT)
    assert not result.verified and result.reason == "nli_weak"


async def test_nli_mild_neutral_passes(monkeypatch):
    # Below the 0.85 strong-neutral bar -> not enough to reject a quote-matched,
    # entity-clean claim.
    _mock_nli(monkeypatch, "neutral", 0.50)
    result = await verify_claim(_NLI_CLAIM, CHUNK_TEXT)
    assert result.verified and result.reason == "ok"


async def test_batched_and_single_nli_agree(monkeypatch):
    # The two code paths must never diverge on the same verdict.
    _mock_nli(monkeypatch, "contradiction", 0.90)
    single = await verify_claim(_NLI_CLAIM, CHUNK_TEXT)
    report = await verify_claims([_NLI_CLAIM], {"c1": CHUNK_TEXT})
    assert report.results[0].verified == single.verified
    assert report.results[0].reason == single.reason == "nli_contradiction"


# ── Fail-closed: required-but-unavailable NLI must refuse, never quote-only ───
# (A1) In an environment where NLI is REQUIRED (prod), the gate must raise rather
# than silently pass claims on quote-match alone.

from app.core.exceptions import VerificationUnavailable  # noqa: E402


async def test_fail_closed_when_nli_required_but_disabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")   # -> nli_required True
    monkeypatch.setattr(settings, "ml_nli_enabled", False)
    monkeypatch.setattr(gate, "nli_available", lambda: False)
    with pytest.raises(VerificationUnavailable):
        await verify_claims([_NLI_CLAIM], {"c1": CHUNK_TEXT})
    with pytest.raises(VerificationUnavailable):
        await verify_claim(_NLI_CLAIM, CHUNK_TEXT)


async def test_fail_closed_when_nli_required_but_model_not_operational(monkeypatch):
    # Flag ON but the model failed to load -> it returns "skipped". Where NLI is
    # required, a broken truth layer is a refusal, not a pass.
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "ml_nli_enabled", True)
    monkeypatch.setattr(gate, "nli_available", lambda: True)

    async def _skipped_single(premise, hypothesis):
        return ("skipped", 0.0)

    async def _skipped_batch(pairs):
        return [("skipped", 0.0) for _ in pairs]

    monkeypatch.setattr(gate, "nli_entailment", _skipped_single)
    monkeypatch.setattr(gate, "nli_entailment_batch", _skipped_batch)
    with pytest.raises(VerificationUnavailable):
        await verify_claims([_NLI_CLAIM], {"c1": CHUNK_TEXT})
    with pytest.raises(VerificationUnavailable):
        await verify_claim(_NLI_CLAIM, CHUNK_TEXT)


def test_assert_verification_ready_refuses_prod_without_nli(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "ml_nli_enabled", False)
    with pytest.raises(RuntimeError, match="ML_NLI_ENABLED"):
        gate.assert_verification_ready()


def test_assert_verification_ready_ok_in_dev(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "ml_nli_enabled", False)
    gate.assert_verification_ready()  # must not raise
