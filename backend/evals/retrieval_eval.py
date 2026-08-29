"""Retrieval-quality evaluation (Phase 3).

The groundedness eval proves the *gate* works (nothing unsupported ships). It
does NOT measure whether the RETRIEVER surfaces the right evidence in the first
place — so a retrieval regression shows up only as more false "gaps", invisibly.
This module closes that: using the golden set's existing ``must_cite_doc``
labels (no new annotation needed), it scores the real hybrid retriever with the
standard IR metrics.

Metrics (document-level binary relevance = the gold doc):
  recall@k : fraction of questions whose gold doc appears in the top-k.
  mrr      : mean reciprocal rank of the first gold-doc chunk.
  ndcg@k   : discounted hit (IDCG = 1, so ndcg = 1/log2(rank+2) or 0).

It exercises the SAME path production uses (query transform → hybrid retrieve),
so the number reflects real retrieval quality, not a toy.
"""

import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.retrieval.hybrid import retrieve
from app.retrieval.query_transform import transform_query

logger = get_logger("evals.retrieval")

_SCHOLARLY = ["paper", "upload"]


async def evaluate_retrieval(
    session: AsyncSession, project_id: str, cases: list[dict],
    doc_map: dict[str, str], *, k: int = 10,
) -> dict:
    """cases: golden supported_questions (each with question + must_cite_doc).
    doc_map: retrieved document_id -> golden doc_id."""
    recall_hits = 0
    rr_sum = 0.0
    ndcg_sum = 0.0
    per_q: list[dict] = []

    for case in cases:
        gold = case["must_cite_doc"]
        tq = await transform_query(case["question"])
        chunks = await retrieve(
            session, project_id, case["question"], source_types=_SCHOLARLY,
            top_k=k, query_variants=tq.variants, hyde_text=tq.hypothetical or None,
        )
        ranked_docs = [doc_map.get(c.document_id, "?") for c in chunks]
        rank = next((i for i, d in enumerate(ranked_docs) if d == gold), None)
        hit = rank is not None
        recall_hits += int(hit)
        rr = 1.0 / (rank + 1) if hit else 0.0
        ndcg = 1.0 / math.log2(rank + 2) if hit else 0.0  # IDCG = 1
        rr_sum += rr
        ndcg_sum += ndcg
        per_q.append({"q": case["question"][:60], "gold": gold,
                      "rank": rank, "hit": hit})
        if not hit:
            logger.warning("gold doc missed in top-k",
                           extra={"q": case["question"][:60], "gold": gold, "k": k})

    n = max(len(cases), 1)
    return {
        "k": k,
        "questions": len(cases),
        f"recall@{k}": round(recall_hits / n, 3),
        "mrr": round(rr_sum / n, 3),
        f"ndcg@{k}": round(ndcg_sum / n, 3),
        "per_question": per_q,
    }
