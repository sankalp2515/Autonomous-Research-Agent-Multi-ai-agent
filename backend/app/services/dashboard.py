"""Per-project observability dashboard aggregation.

One read-mostly endpoint assembling the signals a user needs to TRUST the
project: verification health first, then cost/tokens, latency, retrieval quality,
corpus, provider health, and run history. Everything is aggregated from the
system of record (Postgres) + a little ephemeral state (Redis circuit breaker /
cached report metrics). Signals that genuinely aren't measured are returned as
null with an `available: false` — never faked (same honesty rule as the report).
"""

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Answer, Chunk, Claim, ClaimEvidence, Document, Report, Run
from app.llm.clients import PROVIDERS, provider_configured, provider_rpm
from app.stores import redis_store

logger = get_logger("dashboard")

# Price per 1M tokens (USD), input/output. Free-tier providers are 0. Extend when
# paid providers (Anthropic/Mistral/Nvidia/…) are added so the cost view is real.
_PRICE_PER_M: dict[str, tuple[float, float]] = {
    # provider: (input, output). All current providers are free tier.
}


def _pct(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


async def _trust(session: AsyncSession, project_id: str) -> dict:
    verified_claims = await session.scalar(
        select(func.count(Claim.id)).where(Claim.project_id == project_id)) or 0

    # Evidence aggregates in ONE query (join evidence -> its claim in this project).
    row = (await session.execute(
        select(
            func.count(ClaimEvidence.id),
            func.coalesce(func.sum(case((ClaimEvidence.quote_char_start >= 0, 1), else_=0)), 0),
            func.avg(case((ClaimEvidence.nli_label == "entailment", ClaimEvidence.nli_score),
                          else_=None)),
            func.coalesce(func.sum(case((ClaimEvidence.nli_label == "entailment", 1), else_=0)), 0),
            func.coalesce(func.sum(case(
                (ClaimEvidence.nli_label.in_(["entailment", "neutral", "contradiction"]), 1),
                else_=0)), 0),
            func.coalesce(func.sum(case((ClaimEvidence.nli_label == "contradiction", 1), else_=0)), 0),
        ).select_from(ClaimEvidence)
        .join(Claim, ClaimEvidence.claim_id == Claim.id)
        .where(Claim.project_id == project_id)
    )).one()
    ev_total, quote_ok, avg_entail, entailed, nli_scored, contradictions = row

    # Refusals: chat answers refused + report sections that closed as gaps.
    total_answers = await session.scalar(
        select(func.count(Answer.id)).where(Answer.project_id == project_id)) or 0
    refused_answers = await session.scalar(
        select(func.count(Answer.id)).where(
            Answer.project_id == project_id, Answer.refused.is_(True))) or 0

    reports = (await session.scalars(
        select(Report).where(Report.project_id == project_id))).all()
    section_total = sum(len(r.sections or []) for r in reports)
    section_gaps = sum(1 for r in reports for s in (r.sections or [])
                       if s.get("status") == "gap")

    # Fabricated citations MUST be 0 (structural guarantee): any evidence row that
    # did not quote-match is a contract violation worth surfacing loudly.
    fabricated = int(ev_total) - int(quote_ok)

    return {
        "verified_claims": int(verified_claims),
        "evidence_rows": int(ev_total),
        "fabricated_citations": fabricated,                       # expected 0
        "quote_match_rate": _pct(int(quote_ok), int(ev_total)),
        "avg_entailment_score": round(float(avg_entail), 3) if avg_entail is not None else None,
        "entailment_rate": _pct(int(entailed), int(nli_scored)),
        "contradictions_shipped": int(contradictions),           # expected 0
        "reports": len(reports),
        "section_gap_rate": _pct(section_gaps, section_total),
        "chat_answers": int(total_answers),
        "chat_refusal_rate": _pct(int(refused_answers), int(total_answers)),
    }


def _cost(runs: list[Run]) -> dict:
    tokens_in = sum(int((r.budgets_spent or {}).get("tokens_in", 0)) for r in runs)
    tokens_out = sum(int((r.budgets_spent or {}).get("tokens_out", 0)) for r in runs)
    llm_calls = sum(int((r.budgets_spent or {}).get("llm_calls", 0)) for r in runs)
    # Cost: sum over the (currently all-free) price table; 0 until paid providers.
    est_cost = 0.0
    priced = bool(_PRICE_PER_M)
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "llm_calls": llm_calls,
        "avg_tokens_per_run": round((tokens_in + tokens_out) / len(runs)) if runs else 0,
        "est_cost_usd": round(est_cost, 4) if priced else None,
        "cost_note": "all providers on free tier" if not priced else "estimated",
    }


def _latency(runs: list[Run]) -> dict:
    durs = sorted(int((r.budgets_spent or {}).get("seconds", 0)) for r in runs
                  if (r.budgets_spent or {}).get("seconds"))

    def _p(q: float) -> int | None:
        if not durs:
            return None
        i = min(len(durs) - 1, int(q * len(durs)))
        return durs[i]

    # Per-node average across runs (from each run's checkpointed node_seconds).
    node_tot: dict[str, float] = {}
    node_cnt: dict[str, int] = {}
    for r in runs:
        for node, secs in ((r.checkpoint or {}).get("node_seconds", {}) or {}).items():
            node_tot[node] = node_tot.get(node, 0.0) + float(secs)
            node_cnt[node] = node_cnt.get(node, 0) + 1
    per_node = {n: round(node_tot[n] / node_cnt[n], 1) for n in node_tot}
    return {
        "runs_measured": len(durs),
        "p50_seconds": _p(0.5),
        "p95_seconds": _p(0.95),
        "avg_seconds": round(sum(durs) / len(durs)) if durs else None,
        "per_node_avg_seconds": per_node,
    }


async def _retrieval(project_id: str, reports: list[Report]) -> dict:
    # Read the latest report's CACHED eval metrics if present (computing fresh is
    # expensive — the dashboard stays cheap and honest-null when absent).
    import json
    latest = max(reports, key=lambda r: r.created_at, default=None)
    if latest is None:
        return {"available": False}
    cached = await redis_store.cache_get(f"metrics:{latest.id}")
    if not cached:
        return {"available": False, "note": "open the latest report's metrics to populate"}
    m = json.loads(cached).get("metrics", {})
    return {
        "available": True,
        "report_id": latest.id,
        "context_precision": m.get("context_precision", {}).get("value"),
        "context_recall": m.get("context_recall", {}).get("value"),
        "answer_relevance": m.get("answer_relevance", {}).get("value"),
        "faithfulness": m.get("faithfulness", {}).get("value"),
    }


async def _corpus(session: AsyncSession, project_id: str) -> dict:
    by_status = dict((await session.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.project_id == project_id).group_by(Document.status)
    )).all())
    abstract_only = await session.scalar(
        select(func.count(Document.id)).where(
            Document.project_id == project_id, Document.abstract_only.is_(True))) or 0
    total_chunks = await session.scalar(
        select(func.count(Chunk.id)).where(Chunk.project_id == project_id)) or 0
    embedded_chunks = await session.scalar(
        select(func.count(Chunk.id)).where(
            Chunk.project_id == project_id, Chunk.embedded.is_(True))) or 0
    return {
        "documents_by_status": {k: int(v) for k, v in by_status.items()},
        "documents_total": int(sum(by_status.values())),
        "abstract_only": int(abstract_only),
        "chunks_total": int(total_chunks),
        "chunks_embedded": int(embedded_chunks),
        "chunks_cold": int(total_chunks) - int(embedded_chunks),
    }


async def _providers() -> list[dict]:
    out = []
    for name in PROVIDERS:
        configured = provider_configured(name)
        out.append({
            "provider": name,
            "configured": configured,
            "circuit_open": (await redis_store.circuit_open(name)) if configured else False,
            "rpm": provider_rpm(name) if configured else 0,
        })
    return out


def _run_history(runs: list[Run], limit: int = 10) -> list[dict]:
    recent = sorted(runs, key=lambda r: r.created_at, reverse=True)[:limit]
    out = []
    for r in recent:
        b = r.budgets_spent or {}
        gaps = sum(1 for s in ((r.checkpoint or {}).get("sections", []) or [])
                   if s.get("status") == "gap")
        out.append({
            "id": r.id,
            "query": (r.query or "")[:100],
            "status": r.status,
            "seconds": b.get("seconds"),
            "tokens": int(b.get("tokens_in", 0)) + int(b.get("tokens_out", 0)),
            "llm_calls": b.get("llm_calls"),
            "report_id": r.report_id,
            "gaps": gaps,
            "resumable": r.status in ("failed", "running", "queued"),
            "created_at": r.created_at.isoformat(),
        })
    return out


async def build_dashboard(session: AsyncSession, project_id: str) -> dict:
    runs = (await session.scalars(
        select(Run).where(Run.project_id == project_id))).all()
    reports = (await session.scalars(
        select(Report).where(Report.project_id == project_id))).all()
    return {
        "project_id": project_id,
        "trust": await _trust(session, project_id),
        "cost": _cost(list(runs)),
        "latency": _latency(list(runs)),
        "retrieval": await _retrieval(project_id, list(reports)),
        "corpus": await _corpus(session, project_id),
        "providers": await _providers(),
        "runs": _run_history(list(runs)),
    }
