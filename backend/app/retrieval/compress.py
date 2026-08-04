"""Stage 6 of the RAG pipeline: context compression.

Replaces blunt truncation (`text[:2400]`, which decapitates a chunk mid-idea
and wastes budget on boilerplate) with query-aware EXTRACTIVE selection:

  1. split the chunk into sentences
  2. score each sentence against the query (lexical overlap + position prior)
  3. drop near-duplicate sentences seen in earlier chunks
  4. keep the best sentences, in original order, within a char budget

NON-NEGOTIABLE: compression is **extractive only** — sentences are kept
verbatim, never paraphrased or summarised. The verification gate matches the
model's quote against the ORIGINAL chunk text, so an abstractive summary would
make every quote fail. Keeping sentences byte-identical means a quote drawn
from compressed context still matches the full chunk.

Deterministic and dependency-free: no LLM call, no model load.
"""

import re

# Sentence split that respects common abbreviations and decimals well enough
# for prose; deliberately simple over a heavyweight NLP dependency.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_TOKEN = re.compile(r"[a-z0-9]+")

# Sentences shorter than this are usually headings/artifacts, not evidence.
_MIN_SENT_CHARS = 40


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 2}


def split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def _similarity(a: set[str], b: set[str]) -> float:
    """Jaccard overlap — used both for query relevance and dedup."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compress_chunk(
    text: str,
    query: str,
    *,
    budget_chars: int = 1400,
    seen: set[frozenset] | None = None,
    dedup_threshold: float = 0.8,
) -> str:
    """Query-aware extractive compression of one chunk.

    `seen` accumulates token-sets of already-emitted sentences across chunks so
    the same finding repeated in five papers doesn't consume the whole budget.
    """
    if not text:
        return ""
    if len(text) <= budget_chars and seen is None:
        return text  # nothing to gain

    q_tokens = _tokens(query)
    sentences = split_sentences(text)
    scored: list[tuple[float, int, str]] = []
    for idx, sent in enumerate(sentences):
        s_tokens = _tokens(sent)
        if len(sent) < _MIN_SENT_CHARS and idx > 0:
            continue
        relevance = _similarity(q_tokens, s_tokens)
        # Mild position prior: opening sentences carry the chunk's thesis.
        position = 0.15 * (1.0 - min(idx, 10) / 10.0)
        scored.append((relevance + position, idx, sent))

    if not scored:
        return text[:budget_chars]

    scored.sort(key=lambda t: t[0], reverse=True)
    chosen: list[tuple[int, str]] = []
    dropped_as_redundant = False
    used = 0
    for _score, idx, sent in scored:
        s_tokens = frozenset(_tokens(sent))
        if seen is not None and any(
            _similarity(set(s_tokens), set(prev)) >= dedup_threshold for prev in seen
        ):
            dropped_as_redundant = True
            continue  # redundant with something already in context
        if used + len(sent) > budget_chars and chosen:
            continue
        chosen.append((idx, sent))
        used += len(sent) + 1
        if seen is not None:
            seen.add(s_tokens)
        if used >= budget_chars:
            break

    if not chosen:
        # Distinguish the two ways we can end up empty:
        #  - everything was redundant  -> the chunk genuinely adds nothing;
        #    return "" so the caller can drop it and free budget for others.
        #    (Returning the full text here silently defeated dedup entirely.)
        #  - nothing scored (odd input) -> fall back to plain truncation.
        return "" if dropped_as_redundant else text[:budget_chars]
    # Restore document order so the passage still reads naturally.
    chosen.sort(key=lambda t: t[0])
    return " ".join(sent for _idx, sent in chosen)
