"""Veriscope as an MCP (Model Context Protocol) server.

Exposes Veriscope's differentiator — the verification gate — plus paper search
and the full research pipeline as MCP tools, so any MCP client (Claude Desktop,
another agent) can call "verify this claim against its source" or
"produce a verified report" directly. This is the same pattern Wiley's AI
Gateway uses to expose content over MCP; here we expose *verification*.

Run (stdio transport, for Claude Desktop et al.):
    pip install -e ".[mcp,ml]"
    python -m app.mcp_server

Tool tiers:
  - verify_claim / check_over_specification : stateless, need no infra (NLI
    layer needs the [ml] extra; degrades to quote+entity checks without it).
  - find_papers                             : needs only internet (arXiv/S2).
  - deep_research / get_report              : need the full stack (DB + worker).
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("veriscope")


@mcp.tool()
async def verify_claim(claim: str, quote: str, source_text: str) -> dict:
    """Verify a factual claim against a source passage — Veriscope's gate.

    A claim is SUPPORTED only if: (1) the quote appears verbatim in the source,
    (2) the source entails the claim (NLI, when available), and (3) the claim
    names no specific entity (law, tool, org, acronym) absent from the source.

    Args:
        claim: the sentence to check.
        quote: a verbatim span the claim relies on (>=12 chars, copied exactly).
        source_text: the passage the claim is attributed to.
    """
    from app.verification.gate import ClaimInput, verify_claim as _verify
    result = await _verify(ClaimInput(text=claim, chunk_id="src", quote=quote), source_text)
    ev = result.evidence
    return {
        "verified": result.verified,
        "reason": result.reason,  # ok | quote_mismatch | unsupported_entity | nli_* | ...
        "quote_matched": bool(ev and ev.quote_match.ok),
        "nli_label": ev.nli_label if ev else None,
        "nli_score": round(ev.nli_score, 3) if ev else None,
    }


@mcp.tool()
async def check_over_specification(claim: str, source_text: str) -> dict:
    """List specific named entities (laws, tools, orgs, acronyms) the claim
    asserts but the source never mentions — catches 'grounded but mis-
    attributed' claims that quote-match yet over-specify beyond the source."""
    from app.verification.gate import unsupported_entities
    missing = unsupported_entities(claim, source_text)
    return {"over_specified": bool(missing), "unsupported_entities": missing}


@mcp.tool()
async def find_papers(query: str, limit: int = 8) -> list[dict]:
    """Search arXiv + Semantic Scholar for papers matching a query (deduped)."""
    import asyncio

    from app.agents import sources
    results = await asyncio.gather(
        sources.search_arxiv(query, max_results=limit),
        sources.search_semantic_scholar(query, max_results=limit),
        return_exceptions=True,
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        if not isinstance(r, list):
            continue
        for h in r:
            key = (h.arxiv_id or h.doi or h.title.lower().strip())[:120]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({
                "title": h.title, "authors": h.authors[:5], "year": h.year,
                "abstract": (h.abstract or "")[:500], "url": h.url,
                "arxiv_id": h.arxiv_id, "citations": h.citation_count,
            })
    return out[:limit]


@mcp.tool()
async def deep_research(question: str) -> dict:
    """Launch a full verified-research run (search -> ingest -> draft -> gate).
    Returns a run_id + project_id; poll get_report once complete. Requires the
    Veriscope stack (Postgres + Redis + a running worker)."""
    from app.db.models import Project, Run
    from app.db.session import session_scope
    from app.stores import redis_store

    async with session_scope() as session:
        project = Project(owner_id="mcp", name=question[:120], description=question)
        session.add(project)
        await session.flush()
        run = Run(project_id=project.id, query=question)
        session.add(run)
        await session.flush()
        run_id, project_id = run.id, project.id
    await redis_store.enqueue_job("run_pipeline", {"run_id": run_id, "scope": "all"})
    return {"run_id": run_id, "project_id": project_id, "status": "queued"}


@mcp.tool()
async def get_report(report_id: str) -> dict:
    """Fetch a completed verified report: per-section claims with their source
    titles, plus honestly-stated evidence gaps."""
    from sqlalchemy import select

    from app.db.models import Chunk, Claim, ClaimEvidence, Document, Report
    from app.db.session import session_scope

    async with session_scope() as session:
        report = await session.get(Report, report_id)
        if report is None:
            return {"error": "report not found"}
        sections = []
        for s in report.sections:
            claims = []
            for cid in s.get("claim_ids", []):
                claim = await session.get(Claim, cid)
                if not claim:
                    continue
                ev = (await session.scalars(
                    select(ClaimEvidence).where(ClaimEvidence.claim_id == cid))).first()
                src = ""
                if ev:
                    chunk = await session.get(Chunk, ev.chunk_id)
                    if chunk:
                        doc = await session.get(Document, chunk.document_id)
                        src = doc.title if doc else ""
                claims.append({"text": claim.text, "source": src})
            sections.append({
                "heading": s["heading"], "status": s.get("status"),
                "gap_note": s.get("gap_note", ""), "claims": claims,
            })
        return {"title": report.title, "confidence": report.confidence,
                "sections": sections}


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
