"""Markdown scaffolding must not cost a true finding its citation.

`pymupdf4llm` renders a paper's tables AS MARKDOWN. That is why table findings
are extractable at all — and it is also why they were being refused: the stored
chunk reads

    |RAPTOR (2024)<br>10,142,221|20396.49s|-|

while the model quoting that same row writes "RAPTOR (2024) 10,142,221". Same
characters, different scaffolding, and `match_quote` scored it a mismatch.
Measured on the GraphRAG calibration report, 15 of 34 gate refusals were
`quote_mismatch`, several of them exactly this — correctly-sourced numbers
discarded because a pipe sat where a space would be.

THE LINE THIS MUST NOT CROSS. Stripping scaffolding is a normalization, because
the pipes and emphasis runs are inserted by OUR parser and are not in the paper.
It must never become a relaxation: a paraphrase, a changed number or an invented
clause has to fail exactly as hard as before. Both directions are pinned below.
"""

import pytest

from app.verification.quote_match import match_quote, normalize


# ── the refusals this recovers ───────────────────────────────────────────

TABLE_CHUNK = (
    "### **4.1 Evaluation of graph construction**\n"
    "|Method<br>Token cost ofgraph construction|Time cost ofgraph construction|\n"
    "|---|---|\n"
    "|**RAPTOR (2024)**<br>10,142,221|20396.49s|\n"
    "|KGP (2024)<br>15,271,633|17318.07s|\n"
    "|LightRAG (2024)<br>83,909,073|12459.51s|\n"
)


def test_a_table_row_quoted_without_its_pipes_now_matches():
    m = match_quote("RAPTOR (2024) 10,142,221 20396.49s", TABLE_CHUNK)
    assert m.ok and m.method == "exact"


def test_the_span_still_addresses_the_real_source_text():
    """The reader clicks through to a highlighted region of the ORIGINAL chunk,
    so offsets must survive the stripping. A regex pre-pass would have shifted
    every offset after the first pipe and highlighted the wrong row."""
    m = match_quote("KGP (2024) 15,271,633", TABLE_CHUNK)
    assert m.ok
    span = TABLE_CHUNK[m.char_start : m.char_end]
    assert "KGP (2024)" in span and "15,271,633" in span


def test_emphasis_runs_do_not_break_a_quote():
    m = match_quote(
        "The multi-scale structure achieves logarithmic search complexity",
        "the bottom layer containing all vectors. The **multi-scale structure** "
        "achieves _logarithmic search complexity_ relative to corpus size.",
    )
    assert m.ok and m.method == "exact"


# ── the line it must not cross ───────────────────────────────────────────

def test_a_changed_number_still_fails():
    """The failure mode that matters most: scaffolding is noise, a digit is not."""
    assert not match_quote("RAPTOR (2024) 10,142,999 20396.49s", TABLE_CHUNK).ok


def test_a_paraphrase_still_fails():
    assert not match_quote(
        "RAPTOR had the highest token cost of any method evaluated", TABLE_CHUNK
    ).ok


def test_a_row_assembled_from_two_different_rows_still_fails():
    """Reading one method's name against another's number is the specific
    fabrication a table invites; stripping pipes must not enable it."""
    assert not match_quote("RAPTOR (2024) 15,271,633", TABLE_CHUNK).ok


# ── identifiers are content, not emphasis ────────────────────────────────

@pytest.mark.parametrize("text", ["snake_case", "alpha_t", "P_max", "x_1 and y_2"])
def test_underscores_inside_identifiers_are_preserved(text):
    """Stripping `_` unconditionally would fuse `alpha_t` to `alphat` — silently
    renaming symbols in a corpus that is full of them, on both sides of the
    comparison, so the damage would never surface as a failing match."""
    assert "_" in normalize(text)


def test_underscores_used_as_emphasis_are_dropped():
    assert normalize("_italic phrase_") == "italic phrase"


def test_a_quote_is_still_rejected_when_it_is_too_short():
    """Scaffolding removal shortens the normalized quote; the unfalsifiable-quote
    floor must be applied to what remains, not to the raw string."""
    assert not match_quote("|**a**|", TABLE_CHUNK).ok


# ── the two normalizers can never disagree ───────────────────────────────

@pytest.mark.parametrize("text", [
    TABLE_CHUNK,
    "improve-\nment across  runs",
    "ﬁrst ligature and “curly” quotes — dashes",
    "_alpha_ **beta** `gamma` |delta|",
])
def test_normalize_agrees_with_the_offset_mapped_form(text):
    """`normalize` (quote side) and `_norm_with_map` (chunk side) were parallel
    hand-written copies of one ruleset, so an edit to either silently broke
    matching until both were updated. They are now derived from one another;
    this pins that."""
    from app.verification.quote_match import _norm_with_map

    assert normalize(text) == _norm_with_map(text)[0]


def test_every_offset_maps_inside_the_original_string():
    from app.verification.quote_match import _norm_with_map

    norm, omap = _norm_with_map(TABLE_CHUNK)
    assert len(norm) == len(omap)
    assert all(0 <= i < len(TABLE_CHUNK) for i in omap)
    assert omap == sorted(omap)
