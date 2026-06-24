"""Quote matching is trust-critical: exhaustive tests.

If any of these fail, the system can either ship a fabricated quote
(false positive) or reject honest drafts until budget exhaustion
(false negative). Both are product-breaking.
"""

from app.verification.quote_match import match_quote, normalize

CHUNK = (
    "We evaluate the proposed method on three benchmarks. "
    "The model achieves a 14.2% improvement over the baseline on GLUE, "
    "while using 40% fewer parameters. However, performance degrades "
    "significantly on out-of-distribution inputs, suggesting limited "
    "generalization beyond the training distribution."
)


def test_exact_match():
    m = match_quote("achieves a 14.2% improvement over the baseline", CHUNK)
    assert m.ok and m.method == "exact"
    assert CHUNK[m.char_start:m.char_end].startswith("achieves a 14.2%")


def test_case_and_whitespace_insensitive():
    m = match_quote("ACHIEVES A  14.2%   improvement", CHUNK)
    assert m.ok


def test_curly_quotes_and_dashes_normalize():
    chunk = "The “gold–standard” approach—as described—is robust."
    m = match_quote('the "gold-standard" approach-as described-is robust', chunk)
    assert m.ok


def test_pdf_hyphenation_repaired():
    chunk = "the model shows improve-\nment across tasks and bench-\nmarks tested"
    m = match_quote("shows improvement across tasks and benchmarks", chunk)
    assert m.ok


def test_ligatures_normalize():
    chunk = "The eﬃcient ﬁne-tuning workﬂow scales well."
    m = match_quote("The efficient fine-tuning workflow scales well.", chunk)
    assert m.ok


def test_fabricated_quote_rejected():
    m = match_quote("the model achieves a 99.9% improvement over GPT-4", CHUNK)
    assert not m.ok
    assert m.char_start == -1


def test_paraphrase_rejected():
    m = match_quote(
        "the approach performs about fourteen percent better than baseline methods",
        CHUNK,
    )
    assert not m.ok


def test_too_short_quote_rejected():
    # Unfalsifiable micro-quotes must be rejected even if present.
    assert not match_quote("the model", CHUNK).ok
    assert not match_quote("", CHUNK).ok


def test_fuzzy_tolerates_minor_parser_noise():
    noisy_quote = "performance degrades signiﬁcantly on out-of-distribution inputs"
    m = match_quote(noisy_quote, CHUNK)
    assert m.ok


def test_offsets_point_into_original_text():
    quote = "using 40% fewer parameters"
    m = match_quote(quote, CHUNK)
    assert m.ok
    assert normalize(CHUNK[m.char_start:m.char_end]) == normalize(quote)


def test_quote_longer_than_chunk_rejected():
    m = match_quote(CHUNK + " plus invented trailing content here", "short chunk text only")
    assert not m.ok


def test_unicode_nbsp_and_zero_width():
    chunk = "uses 40% fewer​ parameters overall"
    m = match_quote("uses 40% fewer parameters overall", chunk)
    assert m.ok
