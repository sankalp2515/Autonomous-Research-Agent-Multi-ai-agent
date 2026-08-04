"""Advanced-RAG stage tests: context compression (6) and PII masking (9.3).

Both are deterministic and dependency-free, so they're unit-testable without a
model or a database.
"""

from app.core.pii import find_pii, mask_pii
from app.retrieval.compress import compress_chunk, split_sentences

CHUNK = (
    "Retrieval-augmented generation grounds outputs in retrieved passages. "
    "The authors evaluate on three benchmarks using a frozen retriever. "
    "RAG reduced factual errors by 37% compared to closed-book generation. "
    "All experiments ran on eight A100 GPUs for roughly twelve hours. "
    "Funding was provided by an internal research grant."
)


# ── Stage 6: context compression ────────────────────────────────────────

def test_split_sentences_basic():
    assert len(split_sentences(CHUNK)) == 5


def test_compression_keeps_query_relevant_sentence():
    out = compress_chunk(CHUNK, "how much did RAG reduce factual errors?",
                         budget_chars=160, seen=set())
    assert "37%" in out                      # the answer survives
    assert len(out) <= len(CHUNK)


def test_compressed_text_is_verbatim_substring_of_source():
    """Non-negotiable: compression must be EXTRACTIVE, or quote-match breaks."""
    out = compress_chunk(CHUNK, "factual errors benchmarks", budget_chars=200, seen=set())
    for sentence in split_sentences(out):
        assert sentence in CHUNK, f"compression altered text: {sentence!r}"


def test_compression_respects_budget():
    out = compress_chunk(CHUNK, "GPUs", budget_chars=120, seen=set())
    assert len(out) <= 260  # one sentence may overshoot slightly; never the whole chunk
    assert len(out) < len(CHUNK)


def test_cross_chunk_deduplication():
    seen: set[frozenset] = set()
    first = compress_chunk(CHUNK, "factual errors", budget_chars=400, seen=seen)
    assert first
    # The identical chunk seen again contributes (almost) nothing new.
    second = compress_chunk(CHUNK, "factual errors", budget_chars=400, seen=seen)
    assert len(second) < len(first)


def test_empty_and_short_input_safe():
    assert compress_chunk("", "q") == ""
    assert compress_chunk("Short text.", "q") == "Short text."


# ── Stage 9.3: PII masking ──────────────────────────────────────────────

def test_masks_email_and_phone():
    out = mask_pii("Contact jane.doe@example.com or 555-123-4567 about the study")
    assert "jane.doe@example.com" not in out
    assert "555-123-4567" not in out
    assert "[REDACTED:EMAIL]" in out


def test_masks_provider_api_keys():
    for secret in ("sk-abcdefghijklmnopqrstuvwx", "gsk_abcdefghijklmnopqrstuvwxyz12",
                   "hf_abcdefghijklmnopqrstuvwxyz12"):
        out = mask_pii(f"my key is {secret} ok")
        assert secret not in out
        assert "[REDACTED:API_KEY]" in out


def test_masking_is_idempotent():
    once = mask_pii("mail me at a@b.co")
    assert mask_pii(once) == once


def test_clean_research_question_is_untouched():
    q = "How does JWT authentication work in Spring Security?"
    assert mask_pii(q) == q
    assert find_pii(q) == []


def test_find_pii_reports_kinds_without_values():
    kinds = find_pii("reach me at a@b.com")
    assert "EMAIL" in kinds
