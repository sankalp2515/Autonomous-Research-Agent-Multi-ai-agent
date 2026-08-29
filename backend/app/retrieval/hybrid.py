"""Hybrid retrieval: dense (Qdrant) + BM25 (rank-bm25) -> RRF fusion ->
optional cross-encoder rerank. Carried from v1; the cross-encoder's role
is strictly relevance ordering here, never truth.

Closed-corpus guarantee: every path filters by project_id.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Chunk, Document
from app.ml.local_models import embed_texts, rerank
from app.stores.qdrant_store import search as qdrant_search

logger = get_logger("retrieval")

_TOKEN = re.compile(r"[a-z0-9]+")

# Per-project BM25 index cache. The lexical index was previously TOKENIZED and
# rebuilt from scratch on EVERY query — O(corpus) work per request, the clearest
# retrieval-side scalability defect. We now cache the built index keyed on a
# cheap content signature (chunk count + a hash of the id set); a hit skips the
# rebuild entirely, a corpus change (ingest/delete) misses and rebuilds once.
# Bounded LRU so memory stays flat across many projects.
_BM25_CACHE: "OrderedDict[str, tuple[int, list[str], BM25Okapi]]" = None  # type: ignore
_BM25_CACHE_MAX = 32


def _bm25_signature(ids: list[str]) -> int:
    # Order-independent, cheap: sum of per-id hashes + count. Distinguishes a
    # delete+add that keeps the count identical from a truly unchanged corpus.
    return (len(ids) << 1) ^ hash(frozenset(ids))


def _get_bm25(cache_key: str, ids: list[str], tokens_fn) -> tuple[list[str], BM25Okapi]:
    """Returns (aligned_ids, bm25). The aligned_ids order MUST be used to map
    BM25 scores back to chunk ids — it is the order the index was built with,
    which on a cache hit is the cached order, not the caller's fresh dict order.

    `cache_key` is the project PLUS the retrieval filters, because a filtered
    subset is a different index over different ids. Keying on the project alone
    is why filtered calls previously had to bypass the cache entirely (they
    would have poisoned the shared entry) — and every call the PIPELINE makes is
    filtered, so in practice the cache never served the hot path: each of the
    ~6 section retrievals re-tokenized the whole corpus. Keying by filter lets
    them share an entry with each other instead.

    Correctness is unchanged: the signature is computed from the ids actually
    loaded on THIS call, so an ingest mid-run misses and rebuilds.
    """
    global _BM25_CACHE
    if _BM25_CACHE is None:
        _BM25_CACHE = OrderedDict()
    sig = _bm25_signature(ids)
    cached = _BM25_CACHE.get(cache_key)
    if cached and cached[0] == sig:
        _BM25_CACHE.move_to_end(cache_key)
        return cached[1], cached[2]
    bm25 = BM25Okapi(tokens_fn())  # rebuild only on a corpus change
    _BM25_CACHE[cache_key] = (sig, ids, bm25)
    _BM25_CACHE.move_to_end(cache_key)
    while len(_BM25_CACHE) > _BM25_CACHE_MAX:
        _BM25_CACHE.popitem(last=False)
    return ids, bm25


def _bm25_cache_key(project_id: str, source_types, document_ids,
                    published_after, published_before) -> str:
    """One entry per (project, filter-set). Per-document scopes are excluded
    from the shared cache below, so this only ever fans out over the handful of
    source_type/year combinations a run actually uses."""
    st = ",".join(sorted(source_types)) if source_types else "-"
    return f"{project_id}|{st}|{published_after or 0}|{published_before or 0}"


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    section: str
    page_start: int
    page_end: int
    text: str
    score: float
    abstract_only: bool = False
    source_type: str = ""
    citation_count: int = 0
    year: int | None = None


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion over id rankings."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


async def retrieve(
    session: AsyncSession,
    project_id: str,
    query: str,
    *,
    top_k: int | None = None,
    use_rerank: bool = True,
    source_types: list[str] | None = None,
    document_ids: list[str] | None = None,
    max_per_doc: int | None = None,
    published_after: int | None = None,
    published_before: int | None = None,
    query_variants: list[str] | None = None,
    hyde_text: str | None = None,
) -> list[RetrievedChunk]:
    """source_types restricts the evidence class (e.g. ["paper", "upload"]
    for scholarly evidence vs ["repo", "blog"] for practitioner signal) -
    evidence classes are never mixed inside one drafting context.

    published_after (a year) hard-filters to sources at least that recent -
    the user's chosen time window. When unset, no filter is applied but the
    recency prior still favors newer work (data-quality default)."""
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    fetch_n = max(top_k * 3, 30)

    # Corpus text from the system of record.
    stmt = (
        select(Chunk, Document.title, Document.abstract_only, Document.source_type,
               Document.meta, Document.year)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.project_id == project_id, Document.status == "indexed")
    )
    if source_types:
        stmt = stmt.where(Document.source_type.in_(source_types))
    if published_after:
        # Time window: only sources at/after the chosen year (undated sources
        # are kept, never silently dropped - abstract_only labeling handles honesty).
        stmt = stmt.where((Document.year >= published_after) | (Document.year.is_(None)))
    if published_before:
        # Upper bound of a year range: exclude anything published after it, so a
        # prior-run paper outside the window can't be resurfaced into this report.
        stmt = stmt.where((Document.year <= published_before) | (Document.year.is_(None)))
    if document_ids:
        # Per-document scope ("Ask this paper"): retrieve only within these docs.
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    by_id = {chunk.id: (chunk, title, abstract_only, source_type, meta or {}, year)
             for chunk, title, abstract_only, source_type, meta, year in rows}

    # Lexical ranking (BM25 over the project corpus). Tokens include the
    # document title + section ('contextual retrieval'), so a chunk is
    # matchable by the paper/section it belongs to, not just its bare words.
    # The built index is CACHED per project (see _get_bm25) so this O(corpus)
    # tokenize+build runs once per corpus change, not once per query.
    _fresh_ids = list(by_id.keys())

    def _build_tokens() -> list[list[str]]:
        return [_tokenize(f"{by_id[cid][1]} {by_id[cid][0].section} {by_id[cid][0].text}")
                for cid in _fresh_ids]

    # A per-DOCUMENT scope is deliberately not cached: extraction walks every
    # paper once, so each entry would be built, used once and evicted — pure
    # overhead, and it would thrash the LRU for the section-level entries that
    # DO repeat. Everything else (the section-drafting path, which re-queries
    # the same filtered corpus once per section) is cached by filter.
    if document_ids:
        ids, bm25 = _fresh_ids, BM25Okapi(_build_tokens())
    else:
        ids, bm25 = _get_bm25(
            _bm25_cache_key(project_id, source_types, document_ids,
                            published_after, published_before),
            _fresh_ids, _build_tokens)

    # Multi-query lexical ranking: each transformed variant produces its own
    # BM25 ranking, all fused below. One phrasing missing the corpus's
    # vocabulary no longer sinks retrieval.
    lexical_rankings: list[list[str]] = []
    for variant in (query_variants or [query]):
        scores = bm25.get_scores(_tokenize(variant))
        lexical_rankings.append([cid for _, cid in sorted(
            zip(scores, ids), key=lambda t: t[0], reverse=True)][:fetch_n])

    # Dense ranking (Qdrant ANN, project-filtered). We embed the query, the
    # HyDE passage (answer-shaped text matches answer-shaped chunks better than
    # a question does), AND the transformed variants / decomposed sub-questions
    # so each atomic part of a compound question gets its own dense ranking —
    # not just its own BM25 ranking. Local embeddings, so the extra cost is
    # a few CPU-cheap encodes, not API calls.
    dense_inputs = [query] + ([hyde_text] if hyde_text else [])
    _seen_dense = {query.strip().lower()}
    for v in (query_variants or [])[1:5]:  # skip original (== query); cap the fan-out
        vl = (v or "").strip().lower()
        if vl and vl not in _seen_dense:
            _seen_dense.add(vl)
            dense_inputs.append(v)
    dense_rankings: list[list[str]] = []
    try:
        vecs = await embed_texts(dense_inputs)
        for vec in vecs:
            # Push the document filter DOWN to the store when the caller scoped
            # to specific documents; otherwise the ANN budget is spent on the
            # whole project and the scoped document's chunks rarely survive.
            hits = await qdrant_search(vec, project_id, limit=fetch_n * 2,
                                       document_ids=document_ids)
            dense_rankings.append([cid for cid, _ in hits if cid in by_id])
    except Exception:
        logger.exception("dense retrieval failed; degrading to lexical only")

    fused = rrf_fuse([r for r in (*dense_rankings, *lexical_rankings) if r],
                     k=settings.rrf_k)
    candidates = sorted(fused, key=fused.get, reverse=True)[: max(top_k * 2, 20)]
    candidates = [cid for cid in candidates if cid in by_id]

    # Cross-encoder rerank (relevance, primary signal) blended with a mild
    # citation-count prior so that, among comparably relevant passages, the
    # more-cited paper ranks higher. Weight kept small: relevance dominates,
    # citations only break near-ties (never override a clearly better match).
    import math
    from datetime import datetime, timezone

    _cur_year = datetime.now(timezone.utc).year

    def _cite_boost(cid: str) -> float:
        cc = by_id[cid][4].get("citation_count") or 0
        return math.log1p(cc)  # 0 for uncited, ~grows slowly with citations

    def _recency_boost(cid: str) -> float:
        """0..1: 1 for this year, decaying linearly to 0 at the horizon.
        Undated sources get a neutral mid credit so they aren't buried."""
        year = by_id[cid][5]
        if not year:
            return 0.4
        age = max(0, _cur_year - int(year))
        return max(0.0, 1.0 - age / max(1, settings.recency_horizon_years))

    def _priors(cid: str) -> float:
        return (settings.citation_weight * _cite_boost(cid)
                + settings.recency_weight * _recency_boost(cid))

    if use_rerank and candidates:
        try:
            ce_scores = await rerank(query, [by_id[cid][0].text for cid in candidates])
            blended = [(s + _priors(cid), cid) for s, cid in zip(ce_scores, candidates)]
            candidates = [cid for _, cid in sorted(blended, key=lambda t: t[0], reverse=True)]
        except Exception:
            logger.exception("rerank failed; using RRF order")
    elif candidates:
        candidates = sorted(
            candidates,
            key=lambda cid: fused.get(cid, 0.0) + 0.01 * _priors(cid),
            reverse=True,
        )

    # Diversity cap: keep at most max_per_doc chunks per document so a
    # corpus-wide question ("across all papers") draws on many sources
    # instead of clustering on whichever single paper matched hardest.
    if max_per_doc:
        per_doc: dict[str, int] = {}
        diversified: list[str] = []
        for cid in candidates:
            d = by_id[cid][0].document_id
            if per_doc.get(d, 0) >= max_per_doc:
                continue
            per_doc[d] = per_doc.get(d, 0) + 1
            diversified.append(cid)
            if len(diversified) >= top_k:
                break
        candidates = diversified

    out: list[RetrievedChunk] = []
    for cid in candidates[:top_k]:
        chunk, title, abstract_only, source_type, meta, year = by_id[cid]
        out.append(RetrievedChunk(
            chunk_id=chunk.id, document_id=chunk.document_id,
            document_title=title or "", section=chunk.section,
            page_start=chunk.page_start, page_end=chunk.page_end,
            text=chunk.text, score=fused.get(cid, 0.0),
            abstract_only=bool(abstract_only),
            source_type=source_type or "",
            citation_count=int(meta.get("citation_count") or 0),
            year=int(year) if year else None,
        ))
    return out
