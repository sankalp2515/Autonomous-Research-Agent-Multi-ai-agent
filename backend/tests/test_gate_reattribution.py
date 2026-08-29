"""A quote in the wrong envelope is a bookkeeping slip, not a fabrication.

The drafter receives many passages in one prompt and occasionally returns a
verbatim quote under a neighbouring passage's chunk_id. The gate used to reject
that as `quote_mismatch` — discarding a true, properly sourced finding because
the label was crossed. On a live run this was the second-largest bucket of lost
evidence after the entity-guard artifact.

The gate now looks for the quote among the other passages in the same drafting
context and, if exactly ONE contains it, corrects the citation and continues.
That keeps the contract intact — a claim still needs a verbatim span in a real
corpus chunk — and improves it, because the citation the reader clicks now
actually contains the quote.

What must never become possible: a quote that exists in no source passing, or
the gate guessing between two candidate sources.
"""

import pytest

from app.verification.gate import ClaimInput, verify_claims

LOOKUP = {
    "c1": "## 5 Mechanistic Hallucination Mitigation\n\nIn this section we propose a method.",
    "c2": "We do so by encouraging the LM to retrieve more information from MLPs, "
          "and to suppress incorrect information from attention heads.",
    "c3": "An unrelated passage about graph construction cost and indexing time.",
}


@pytest.mark.asyncio
async def test_quote_from_a_neighbouring_passage_is_reattributed():
    report = await verify_claims([ClaimInput(
        "The method encourages the LM to retrieve more information from MLPs.",
        "c1",  # wrong id — the quote lives in c2
        "encouraging the LM to retrieve more information from MLPs",
    )], LOOKUP)
    result = report.results[0]
    assert result.verified, result.reason
    # The citation must now point at the passage that actually contains it.
    assert result.evidence.chunk_id == "c2"


@pytest.mark.asyncio
async def test_a_quote_present_in_no_passage_is_still_refused():
    report = await verify_claims([ClaimInput(
        "The method achieves 99% accuracy.",
        "c1",
        "achieves 99% accuracy on every benchmark we tried",
    )], LOOKUP)
    assert not report.results[0].verified
    assert report.results[0].reason == "quote_mismatch"


@pytest.mark.asyncio
async def test_an_ambiguous_quote_is_refused_rather_than_guessed():
    """Two passages contain the span. Crediting either would be a coin flip, and
    a citation the reader cannot rely on is worse than a withheld finding."""
    lookup = {
        "cited": "A passage that does not contain the sentence in question.",
        "a": "The framework reduces latency substantially under load.",
        "b": "The framework reduces latency substantially under load.",
    }
    report = await verify_claims([ClaimInput(
        "The framework reduces latency.", "cited",
        "reduces latency substantially under load",
    )], lookup)
    assert not report.results[0].verified
    assert report.results[0].reason == "quote_mismatch"


@pytest.mark.asyncio
async def test_a_citation_to_a_chunk_outside_the_corpus_still_fails_first():
    """Layer 1 is unchanged: an id we were never given is a missing citation,
    which is a different (and more serious) fault than a crossed label."""
    report = await verify_claims([ClaimInput(
        "Anything.", "not-a-real-chunk", "encouraging the LM to retrieve",
    )], LOOKUP)
    assert not report.results[0].verified
    assert report.results[0].reason == "missing_chunk"


@pytest.mark.asyncio
async def test_a_correctly_cited_quote_is_untouched():
    report = await verify_claims([ClaimInput(
        "The method suppresses incorrect information from attention heads.",
        "c2",
        "suppress incorrect information from attention heads",
    )], LOOKUP)
    result = report.results[0]
    assert result.verified, result.reason
    assert result.evidence.chunk_id == "c2"
