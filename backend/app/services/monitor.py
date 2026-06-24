"""Standing monitor agent.

Re-checks each project's watch queries for newly-published papers the project
hasn't seen, scores them against the watch by embedding similarity, and stores
the relevant ones as alerts. This is the proactive half of the product: the
corpus keeps growing toward your open questions without you re-searching.

Free-tier friendly: arXiv/Semantic Scholar search + local embedding scoring,
no LLM calls. Deduplicated against the corpus and prior alerts so the same
paper is never surfaced twice.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.agents import sources
from app.core.logging import get_logger
from app.db.models import Document, MonitorAlert, Run, Watch
from app.db.session import session_scope
from app.ingestion.dedup import titles_match
from app.ml.local_models import embed_texts

logger = get_logger("monitor")

SCORE_THRESHOLD = 0.42
MAX_PER_WATCH = 8


async def seed_watches(session, project_id: str) -> int:
    """Create initial watches from the project's latest run's sub-questions."""
    existing = (await session.scalars(
        select(Watch).where(Watch.project_id == project_id)
    )).all()
    if existing:
        return 0
    run = await session.scalar(
        select(Run).where(Run.project_id == project_id,
                          Run.status.in_(["completed", "completed_with_gaps"]))
        .order_by(Run.created_at.desc())
    )
    queries: list[str] = []
    if run and run.checkpoint:
        clar = run.checkpoint.get("clarification") or {}
        queries = list(clar.get("sub_questions") or [])
    if not queries:
        latest = await session.scalar(
            select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
        )
        if latest:
            queries = [latest.query]
    for q in queries[:5]:
        session.add(Watch(project_id=project_id, query=q[:500]))
    return len(queries[:5])


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized


async def run_monitor(project_id: str) -> int:
    """Check all active watches for this project. Returns count of new alerts."""
    async with session_scope() as session:
        watches = [(w.id, w.query) for w in (await session.scalars(
            select(Watch).where(Watch.project_id == project_id, Watch.active == True)  # noqa: E712
        )).all()]
        docs = (await session.scalars(
            select(Document).where(Document.project_id == project_id)
        )).all()
        known_arxiv = {d.arxiv_id for d in docs if d.arxiv_id}
        known_doi = {d.doi for d in docs if d.doi}
        known_titles = [d.title for d in docs if d.title]
        seen_ext = set((await session.scalars(
            select(MonitorAlert.external_id).where(MonitorAlert.project_id == project_id)
        )).all())

    new_total = 0
    for watch_id, query in watches:
        try:
            arx = await sources.search_arxiv(query, max_results=12, sort_by="submittedDate")
            s2 = await sources.search_semantic_scholar(query, max_results=12)
        except Exception:
            logger.warning("monitor search failed", extra={"query": query[:60]})
            arx, s2 = [], []

        cands = []
        for h in arx + s2:
            ext = (h.arxiv_id or h.doi or h.external_id or h.title[:140] or "").strip()
            if not ext or ext in seen_ext:
                continue
            if h.arxiv_id and h.arxiv_id in known_arxiv:
                continue
            if h.doi and h.doi in known_doi:
                continue
            if any(titles_match(h.title, t) for t in known_titles):
                continue
            seen_ext.add(ext)
            cands.append((ext, h))

        kept = []
        if cands:
            try:
                qvec = (await embed_texts([query]))[0]
                cvecs = await embed_texts([f"{h.title}. {h.abstract[:400]}" for _, h in cands])
                scored = [(_cosine(qvec, cv), ext, h) for (ext, h), cv in zip(cands, cvecs)]
            except Exception:
                scored = [(0.5, ext, h) for ext, h in cands]
            scored.sort(key=lambda x: x[0], reverse=True)
            kept = [s for s in scored if s[0] >= SCORE_THRESHOLD][:MAX_PER_WATCH]

        async with session_scope() as session:
            for score, ext, h in kept:
                session.add(MonitorAlert(
                    project_id=project_id, watch_id=watch_id, external_id=ext,
                    title=h.title, url=h.url, pdf_url=h.pdf_url,
                    abstract=h.abstract[:2000], authors=h.authors, year=h.year,
                    arxiv_id=h.arxiv_id, doi=h.doi, score=round(float(score), 3),
                ))
                new_total += 1
            w = await session.get(Watch, watch_id)
            if w:
                w.last_checked = datetime.now(timezone.utc)

    logger.info("monitor run complete",
                extra={"project_id": project_id, "watches": len(watches), "new": new_total})
    return new_total
