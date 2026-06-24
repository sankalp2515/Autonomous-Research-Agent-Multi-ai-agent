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
