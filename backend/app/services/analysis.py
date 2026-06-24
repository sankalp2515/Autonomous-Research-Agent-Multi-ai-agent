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
from app.ml.local_models import nli_available, nli_entailment

logger = get_logger("analysis")

_MAX_CLAIMS = 28          # bound the O(n^2) sweep
_CONTRA_THRESHOLD = 0.75  # NLI contradiction confidence to flag


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

    flagged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a, b = claims[i], claims[j]
            if not a["doc_id"] or a["doc_id"] == b["doc_id"]:
                continue  # only flag DISAGREEMENT BETWEEN sources
            label, score = await nli_entailment(a["text"], b["text"])
            if label == "contradiction" and score >= _CONTRA_THRESHOLD:
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
    logger.info("contradiction scan", extra={"report_id": report_id,
                                            "claims": len(claims), "flagged": len(flagged)})
    return flagged
