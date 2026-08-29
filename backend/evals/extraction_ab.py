"""Live A/B of the evidence-acquisition layer, over an EXISTING corpus.

The retrieval benchmark (evals/evidence_bench.py) proves the passages reach the
extractor. This proves what the extractor then does with them — and, just as
importantly, that the cells it cannot fill are labeled honestly rather than
filled anyway.

WHY REPLAY INSTEAD OF A FRESH RUN. A whole new pipeline run would change the
corpus too (different search results, different screening), and then nothing
could be attributed to the extraction layer. This replays ONLY
`evidence_schema -> extract_evidence` against a corpus that is already ingested,
so the papers are identical to the baseline report's and the extraction stack is
the only variable.

    python -m evals.extraction_ab --report <baseline_report_id>
    python -m evals.extraction_ab --report <id> --legacy    # control arm

`--legacy` disables dimension-directed retrieval and recovery, reproducing the
old single-query behaviour on the same corpus — the control for the comparison.

NOTE: this writes Claim + ClaimEvidence rows exactly as a real run does (they
are what makes each matrix cell click-to-source). It does not create a Report.
"""

import argparse
import asyncio
import json
import sys
import time

from sqlalchemy import select

from app.agents import nodes
from app.agents.state import new_state
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Document, Report, Run
from app.db.session import session_scope


async def _noop(*_a, **_kw):
    """The node decorator checkpoints to Postgres/Redis against a run row this
    replay does not own; the replay is not a run, so that is skipped."""
    return None


async def replay(report_id: str, legacy: bool = False) -> dict:
    settings = get_settings()
    async with session_scope() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise SystemExit(f"no report {report_id}")
        run = await session.get(Run, report.run_id)
        project_id = report.project_id
        query = run.query if run else report.title
        plan = (report.confidence or {}).get("plan") or {}
        # The papers the baseline actually read, in the baseline's own order.
        doc_ids = [r["doc_id"] for r in
                   ((report.confidence or {}).get("evidence_matrix") or [])]
        if not doc_ids:
            doc_ids = list((await session.scalars(
                select(Document.id).where(Document.project_id == project_id,
                                          Document.status == "indexed",
                                          Document.source_type == "paper"))).all())

    if legacy:
        settings.evidence_dimension_retrieval = False
        settings.evidence_recovery_enabled = False

    state = new_state("replay-" + report_id[:8], project_id, query)
    state["clarification"] = {
        "objective": plan.get("objective") or query,
        "domain": "", "sub_questions": plan.get("sub_questions") or [],
    }
    state["paper_doc_ids"] = doc_ids

    # Silence the run-scoped side effects; this replay owns no Run row.
    nodes._checkpoint = _noop
    nodes.publish_progress = _noop

    started = time.time()
    if not legacy:
        await nodes.evidence_schema_node(state)
    await nodes.extract_evidence_node(state)
    elapsed = time.time() - started

    matrix = state.get("evidence_matrix", [])
    return {
        "arm": "legacy" if legacy else "dimension-directed",
        "project_id": project_id,
        "query": query,
        "papers_read": len(doc_ids),
        "studies_extracted": len(matrix),
        "findings": sum(len(r.get("findings", [])) for r in matrix),
        "recovered_findings": sum(1 for r in matrix
                                  for f in r.get("findings", []) if f.get("recovered")),
        "drafted": state.get("evidence_drafted_total", 0),
        "verified": state.get("evidence_verified_total", 0),
        "llm_calls": state.get("llm_calls_used", 0),
        "wall_seconds": round(elapsed, 1),
        "schema": state.get("evidence_schema", {}),
        "funnel": state.get("funnel", {}),
        "coverage_notes": state.get("coverage_notes", []),
        "matrix": matrix,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    configure_logging("WARNING", "console")
    out = await replay(args.report, legacy=args.legacy)

    summary = {k: v for k, v in out.items() if k not in ("matrix", "schema")}
    summary["required_dimensions"] = [
        d["name"] for d in (out["schema"].get("required_dimensions") or [])]
    print(json.dumps(summary, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print("wrote " + args.json)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
