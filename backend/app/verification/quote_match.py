"""Quote exact-match: the mechanism that makes weak free-tier models
trustworthy. The drafting LLM must return a verbatim quote per claim;
this module checks the quote actually exists in the cited chunk.

A model can hallucinate a paraphrase. It cannot fake a quote that
survives normalized exact matching against the source text.

Pure python, zero dependencies, exhaustively unit-tested - this is
trust-critical code.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# Characters PDFs commonly mangle: curly quotes, dashes, ligatures, NBSP.
_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "′": "'",
    "–": "-", "—": "-", "−": "-", "­": "",
    " ": " ", " ": " ", " ": " ", "​": "",
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
})

_WS = re.compile(r"\s+")


@dataclass
class QuoteMatch:
    ok: bool
    method: str          # exact | fuzzy | none
    score: float
    char_start: int      # offsets into the ORIGINAL chunk text, -1 if no match
    char_end: int


# ── Markdown scaffolding is LAYOUT, not content ──────────────────────────
#
# pymupdf4llm renders a paper's tables as markdown, which is why table findings
# are extractable at all — but it means the stored chunk reads
#
#     |RAPTOR (2024)<br>10,142,221|20396.49s|-|
#
# while the model, quoting the same fact in the same document, writes
# "RAPTOR (2024) 10,142,221". Those are the same characters separated by cell
# scaffolding, and the gate was scoring them as a quote mismatch. Measured on
# the GraphRAG calibration report, 15 of 34 refusals were quote_mismatch and
# several were exactly this: TRUE, correctly-sourced table findings thrown away
# because a pipe sits where a space would be.
#
# This is a normalization, not a relaxation. The pipe, the emphasis run and the
# <br> are inserted by OUR parser; they are not in the paper. Removing them on
# BOTH sides compares the text the author actually wrote. A claim still has to
# carry every content character verbatim — nothing here lets a paraphrase pass.
_MD_BREAK = re.compile(r"<br\s*/?>", re.I)
_MD_STRIP = re.compile(r"[*`]+")
# Underscore only where it delimits emphasis (_italic_), never inside an
# identifier: stripping it unconditionally would fuse `snake_case` to
# `snakecase` and `alpha_t` to `alphat`, quietly changing symbol names in a
# corpus full of them.
_MD_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")


def normalize(text: str) -> str:
    """Kept as the single public entry point, but DELEGATES to the offset-mapped
    implementation. These two used to be parallel hand-written copies of the
    same rules — the quote normalized by one and the chunk by the other — so any
    edit to one silently broke matching until both were updated. Deriving one
    from the other makes divergence impossible."""
    return _norm_with_map(text)[0]


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize while keeping a map from normalized index -> original index,
    so a match in normalized space yields offsets into the original chunk."""
    text = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    omap: list[int] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        # ── markdown scaffolding (see the constants above) ───────────────
        # Emitted by our own parser, so it is dropped before comparison and
        # never contributes an offset. Handled HERE rather than in a pre-pass
        # because the index map has to stay aligned to the ORIGINAL chunk —
        # a regex sub would shift every offset after it and point the reader's
        # highlighted span at the wrong characters.
        if ch in "*`":
            i += 1
            continue
        if ch == "<":
            m = _MD_BREAK.match(text, i)
            if m:
                # A cell break separates content: collapse to a space so
                # "RAPTOR<br>10,142,221" reads as two words, not one.
                if out and out[-1] != " ":
                    out.append(" ")
                    omap.append(i)
                i = m.end()
                continue
        if ch == "|":
            if out and out[-1] != " ":
                out.append(" ")
                omap.append(i)
            i += 1
            continue
        if ch == "_":
            prev_alnum = i > 0 and text[i - 1].isalnum()
            next_alnum = i + 1 < n and text[i + 1].isalnum()
            if not (prev_alnum and next_alnum):  # emphasis, not an identifier
                i += 1
                continue
        # hyphenated line break
        if ch == "-" and i + 1 < n:
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] == "\n":
                j += 1
                while j < n and text[j] in " \t\n":
                    j += 1
                i = j
                continue
        ch = ch.translate(_TRANSLATE) or ""
        if not ch:
            i += 1
            continue
        if ch.isspace() or ch == "\n":
            if out and out[-1] != " ":
                out.append(" ")
                omap.append(i)
            i += 1
            continue
        for sub in ch:  # ligatures expand to multiple chars
            out.append(sub.lower())
            omap.append(i)
        i += 1
    # trim trailing space
    while out and out[-1] == " ":
        out.pop()
        omap.pop()
    return "".join(out), omap


def match_quote(quote: str, chunk_text: str, *, fuzzy_threshold: float = 0.92) -> QuoteMatch:
    """Exact normalized substring first; sliding-window fuzzy fallback for
    minor parser noise. Below threshold -> no match, claim fails."""
    quote_n = normalize(quote)
    if not quote_n or len(quote_n) < 12:
        # Too-short quotes are unfalsifiable ("the", "we show") - reject so
        # the drafting prompt is forced to quote substantively.
        return QuoteMatch(False, "none", 0.0, -1, -1)

    chunk_n, omap = _norm_with_map(chunk_text)

    idx = chunk_n.find(quote_n)
    if idx != -1:
        start = omap[idx]
        end_norm = idx + len(quote_n) - 1
        end = omap[end_norm] + 1 if end_norm < len(omap) else len(chunk_text)
        return QuoteMatch(True, "exact", 1.0, start, end)

    # Fuzzy: best window of equal length (± slack) over the chunk.
    qlen = len(quote_n)
    if qlen > len(chunk_n):
        score = SequenceMatcher(None, quote_n, chunk_n).ratio()
        if score >= fuzzy_threshold:
            return QuoteMatch(True, "fuzzy", score, omap[0] if omap else 0, len(chunk_text))
        return QuoteMatch(False, "none", score, -1, -1)

    step = max(qlen // 4, 8)
    best_score, best_at = 0.0, -1
    for at in range(0, len(chunk_n) - qlen + 1, step):
        window = chunk_n[at : at + qlen]
        score = SequenceMatcher(None, quote_n, window).ratio()
        if score > best_score:
            best_score, best_at = score, at
            if score > 0.99:
                break
    # refine around the best coarse hit
    if best_at >= 0:
        lo = max(0, best_at - step)
        hi = min(len(chunk_n) - qlen, best_at + step)
        for at in range(lo, hi + 1):
            window = chunk_n[at : at + qlen]
            score = SequenceMatcher(None, quote_n, window).ratio()
            if score > best_score:
                best_score, best_at = score, at

    if best_score >= fuzzy_threshold and best_at >= 0:
        start = omap[best_at]
        end_norm = min(best_at + qlen - 1, len(omap) - 1)
        end = omap[end_norm] + 1
        return QuoteMatch(True, "fuzzy", best_score, start, end)
    return QuoteMatch(False, "none", best_score, -1, -1)
