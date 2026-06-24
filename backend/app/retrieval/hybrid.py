"""Hybrid retrieval: dense (Qdrant) + BM25 (rank-bm25) -> RRF fusion ->
optional cross-encoder rerank. Carried from v1; the cross-encoder's role
is strictly relevance ordering here, never truth.

Closed-corpus guarantee: every path filters by project_id.
"""

import re
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
) -> list[RetrievedChunk]:
    """source_types restricts the evidence class (e.g. ["paper", "upload"]
    for scholarly evidence vs ["repo", "blog"] for practitioner signal) -
    evidence classes are never mixed inside one drafting context."""
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    fetch_n = max(top_k * 3, 30)

    # Corpus text from the system of record.
    stmt = (
        select(Chunk, Document.title, Document.abstract_only, Document.source_type,
               Document.meta)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.project_id == project_id, Document.status == "indexed")
    )
    if source_types:
        stmt = stmt.where(Document.source_type.in_(source_types))
    if document_ids:
        # Per-document scope ("Ask this paper"): retrieve only within these docs.
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    rows = (await session.execute(stmt)).all()
    if not rows:
        return []
    by_id = {chunk.id: (chunk, title, abstract_only, source_type, meta or {})
             for chunk, title, abstract_only, source_type, meta in rows}

    # Lexical ranking (BM25 over the project corpus). Tokens include the
    # document title + section ('contextual retrieval'), so a chunk is
    # matchable by the paper/section it belongs to, not just its bare words.
    ids = list(by_id.keys())
    corpus_tokens = [
        _tokenize(f"{by_id[cid][1]} {by_id[cid][0].section} {by_id[cid][0].text}")
        for cid in ids
    ]
    bm25 = BM25Okapi(corpus_tokens)
    lex_scores = bm25.get_scores(_tokenize(query))
    lexical_ranked = [cid for _, cid in sorted(
        zip(lex_scores, ids), key=lambda t: t[0], reverse=True)][:fetch_n]

    # Dense ranking (Qdrant ANN, project-filtered). Source-type filtering is
    # applied via by_id membership after fusion.
    dense_ranked: list[str] = []
    try:
        qvec = (await embed_texts([query]))[0]
        dense_ranked = [cid for cid, _ in await qdrant_search(qvec, project_id, limit=fetch_n * 2)
                        if cid in by_id]
    except Exception:
        logger.exception("dense retrieval failed; degrading to lexical only")

    fused = rrf_fuse([r for r in (dense_ranked, lexical_ranked) if r], k=settings.rrf_k)
    candidates = sorted(fused, key=fused.get, reverse=True)[: max(top_k * 2, 20)]
    candidates = [cid for cid in candidates if cid in by_id]

    # Cross-encoder rerank (relevance, primary signal) blended with a mild
    # citation-count prior so that, among comparably relevant passages, the
    # more-cited paper ranks higher. Weight kept small: relevance dominates,
    # citations only break near-ties (never override a clearly better match).
    import math

    def _cite_boost(cid: str) -> float:
        cc = by_id[cid][4].get("citation_count") or 0
        return math.log1p(cc)  # 0 for uncited, ~grows slowly with citations

    if use_rerank and candidates:
        try:
            ce_scores = await rerank(query, [by_id[cid][0].text for cid in candidates])
            blended = [(s + settings.citation_weight * _cite_boost(cid), cid)
                       for s, cid in zip(ce_scores, candidates)]
            candidates = [cid for _, cid in sorted(blended, key=lambda t: t[0], reverse=True)]
        except Exception:
            logger.exception("rerank failed; using RRF order")
    elif candidates:
        candidates = sorted(
            candidates,
            key=lambda cid: fused.get(cid, 0.0) + settings.citation_weight * 0.01 * _cite_boost(cid),
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
        chunk, title, abstract_only, source_type, meta = by_id[cid]
        out.append(RetrievedChunk(
            chunk_id=chunk.id, document_id=chunk.document_id,
            document_title=title or "", section=chunk.section,
            page_start=chunk.page_start, page_end=chunk.page_end,
            text=chunk.text, score=fused.get(cid, 0.0),
            abstract_only=bool(abstract_only),
            source_type=source_type or "",
            citation_count=int(meta.get("citation_count") or 0),
        ))
    return out
