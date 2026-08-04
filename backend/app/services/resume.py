"""Welcome-back / continuity surface.

The persistent-library promise is: a researcher who leaves mid-flight and comes
back should not have to reconstruct where they were. Everything needed is
already durable truth — run checkpoints, episodic memory, monitor alerts,
comparisons — so this service just AGGREGATES it into one orientation payload
the UI shows when a project is opened.

No LLM calls: pure reads, fast, safe to hit on every project open.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    Comparison, Document, Memory, MonitorAlert, Report, Run,
)

logger = get_logger("resume")

_UNFINISHED = ("queued", "running", "failed")


async def build_resume(session: AsyncSession, project_id: str) -> dict:
    # Unfinished / failed runs — resumable from their checkpoint.
    runs = (await session.scalars(
        select(Run).where(Run.project_id == project_id,
                          Run.status.in_(_UNFINISHED))
        .order_by(Run.created_at.desc()).limit(5)
    )).all()
    unfinished = [{
        "run_id": r.id, "query": r.query, "status": r.status,
        "current_node": r.current_node or "queued",
        "resumable": bool(r.checkpoint) or r.status in ("queued", "running"),
        "created_at": r.created_at.isoformat(),
    } for r in runs]

    # Last thing the project worked on (episodic memory), plus any open gaps
    # recorded from prior runs.
    last_episodic = (await session.scalars(
        select(Memory).where(Memory.project_id == project_id,
                             Memory.kind == "episodic")
        .order_by(Memory.created_at.desc()).limit(1)
    )).first()

    latest_report = (await session.scalars(
        select(Report).where(Report.project_id == project_id)
        .order_by(Report.created_at.desc()).limit(1)
    )).first()
    open_gaps: list[str] = []
    if latest_report:
        for s in latest_report.sections:
            if s.get("status") == "gap" and s.get("gap_note"):
                open_gaps.append(f"{s.get('heading', '')}: {s['gap_note']}")

    new_alerts = await session.scalar(
        select(func.count(MonitorAlert.id)).where(
            MonitorAlert.project_id == project_id,
            MonitorAlert.status == "new",
        )
    ) or 0

    doc_count = await session.scalar(
        select(func.count(Document.id)).where(
            Document.project_id == project_id, Document.status == "indexed")
    ) or 0
    comparison_count = await session.scalar(
        select(func.count(Comparison.id)).where(Comparison.project_id == project_id)
    ) or 0

    # Suggested next actions, ranked — the researcher's shortest path back in.
    suggestions: list[dict] = []
    if unfinished:
        suggestions.append({
            "kind": "resume_run", "run_id": unfinished[0]["run_id"],
            "label": f"Resume your unfinished run: “{unfinished[0]['query'][:70]}”",
        })
    if new_alerts:
        suggestions.append({
            "kind": "review_alerts",
            "label": f"{new_alerts} new paper{'s' if new_alerts != 1 else ''} "
                     "matched your watches — review and add.",
        })
    if open_gaps:
        suggestions.append({
            "kind": "close_gap",
            "label": f"Your last report left {len(open_gaps)} open gap"
                     f"{'s' if len(open_gaps) != 1 else ''} — research further.",
        })
    if doc_count >= 2:
        suggestions.append({
            "kind": "compare",
            "label": "Compare papers in your library side-by-side.",
        })

    return {
        "project_id": project_id,
        "doc_count": int(doc_count),
        "comparison_count": int(comparison_count),
        "new_alerts": int(new_alerts),
        "unfinished_runs": unfinished,
        "last_activity": last_episodic.text if last_episodic else "",
        "last_activity_at": last_episodic.created_at.isoformat() if last_episodic else "",
        "open_gaps": open_gaps[:5],
        "latest_report_id": latest_report.id if latest_report else None,
        "suggestions": suggestions,
    }
