"""Cross-source contradiction detection.

Runs the NLI model over pairs of verified claims from *different* documents
in a report. When two grounded claims contradict each other, that tension is
exactly what a researcher needs to see - so we surface the pair with both
sources. Each claim is already quote-verified, so a flagged contradiction is
a real disagreement between sources, not a model hallucination.

Bounded (claim cap + cross-document filter) and cached by the caller so the
O(n^2) NLI sweep runs at most once per report.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Chunk, Claim, ClaimEvidence, Document, Report
from app.services.memory import cosine
from app.ml.local_models import nli_available, nli_entailment_batch

logger = get_logger("analysis")

_MAX_CLAIMS = 40          # bound the pair sweep (cheaper now that pairs are gated)
_CONTRA_THRESHOLD = 0.75  # NLI contradiction confidence to flag
# Two claims can only meaningfully contradict if they are ABOUT the same thing.
# Gating pairs on embedding similarity kills spurious "contradictions" between
# unrelated statements and cuts the O(n^2) NLI cost by an order of magnitude.
_MIN_TOPICAL_SIM = 0.40


async def _report_claims(session: AsyncSession, report: Report) -> list[dict]:
    out: list[dict] = []
    for s in report.sections:
        for cid in s.get("claim_ids", []):
            claim = await session.get(Claim, cid)
            if not claim:
                continue
            ev = (await session.scalars(
                select(ClaimEvidence).where(ClaimEvidence.claim_id == cid)
            )).first()
            doc_id = doc_title = ""
            page = 0
            if ev:
                chunk = await session.get(Chunk, ev.chunk_id)
                if chunk:
                    page = chunk.page_start
                    doc = await session.get(Document, chunk.document_id)
                    if doc:
                        doc_id, doc_title = doc.id, doc.title
            out.append({
                "claim_id": cid, "text": claim.text, "doc_id": doc_id,
                "doc_title": doc_title, "page": page, "section": s.get("heading", ""),
            })
            if len(out) >= _MAX_CLAIMS:
                return out
    return out


async def find_contradictions(session: AsyncSession, report_id: str) -> list[dict]:
    if not nli_available():
        return []
    report = await session.get(Report, report_id)
    if report is None:
        return []
    claims = await _report_claims(session, report)

    # 1. Candidate pairs: different documents AND semantically about the same
    #    thing. Without the topical gate, unrelated claims get NLI-scored and
    #    occasionally flagged as "contradictions" - noise a researcher can't trust.
    embeddings: list[list[float]] | None = None
    try:
        from app.ml.local_models import embed_texts
        embeddings = await embed_texts([c["text"] for c in claims])
    except Exception:
        embeddings = None  # degrade to cross-document filtering only

    pairs: list[tuple[int, int]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            if not a["doc_id"] or a["doc_id"] == b["doc_id"]:
                continue  # only flag DISAGREEMENT BETWEEN sources
            if embeddings and cosine(embeddings[i], embeddings[j]) < _MIN_TOPICAL_SIM:
                continue  # different topics -> cannot contradict
            pairs.append((i, j))
    if not pairs:
        return []

    # 2. Score both directions in ONE batched forward pass (NLI is asymmetric:
    #    A may contradict B without B contradicting A). Take the stronger signal.
    scored = await nli_entailment_batch(
        [(claims[i]["text"], claims[j]["text"]) for i, j in pairs]
        + [(claims[j]["text"], claims[i]["text"]) for i, j in pairs]
    )
    half = len(pairs)

    flagged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for idx, (i, j) in enumerate(pairs):
        best = max(
            (scored[idx], scored[idx + half]),
            key=lambda t: t[1] if t[0] == "contradiction" else -1.0,
        )
        label, score = best
        if label != "contradiction" or score < _CONTRA_THRESHOLD:
            continue
        a, b = claims[i], claims[j]
        key = tuple(sorted((a["claim_id"], b["claim_id"])))
        if key in seen:
            continue
        seen.add(key)
        flagged.append({
            "score": round(score, 3),
            "a": {"claim_id": a["claim_id"], "text": a["text"],
                  "source": a["doc_title"], "page": a["page"]},
            "b": {"claim_id": b["claim_id"], "text": b["text"],
                  "source": b["doc_title"], "page": b["page"]},
        })
    flagged.sort(key=lambda x: x["score"], reverse=True)
    logger.info("contradiction scan", extra={
        "report_id": report_id, "claims": len(claims),
        "pairs_considered": len(pairs), "flagged": len(flagged)})
    return flagged
