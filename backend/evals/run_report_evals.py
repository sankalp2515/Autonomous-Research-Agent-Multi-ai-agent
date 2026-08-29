"""Report-pipeline groundedness eval (audit item A2).

`run_evals.py` covers the single-question CHAT path. This covers the flagship
REPORT path — the draft -> verification-gate -> assemble machinery that turns a
corpus into a cited report — which previously had NO end-to-end eval.

Hermetic by design: the live `research` node hits arXiv / Semantic Scholar and
cannot be reproduced, so we seed a FIXED corpus and drive the real, grounding-
critical nodes (`draft_sections_node` then `assemble_node`) against it. That is
exactly the code that decides what claims ship, so the invariants below are the
ones that matter for trust.

Asserted invariants (release gates):
  * fabricated_evidence == 0    every shipped claim has a quote that exactly
                                matched an in-corpus chunk (quote_char_start>=0).
  * closed_corpus == true       every evidence chunk belongs to THIS project's
                                corpus — no cross-corpus / phantom sources.
  * no_contradictions == true   (NLI on) no shipped claim is NLI-contradicted.
  * gap_honesty == true         the deliberately-unanswerable section is a
                                labeled gap, not a fabricated answer.
  * answered_rate >= 0.8        answerable sections actually produced claims
                                (guards against the gate refusing everything).

Usage:  python -m evals.run_report_evals
Needs:  docker-compose up (postgres/redis/qdrant) + LLM API keys, same as
        run_evals.py. Exit code 1 on any gate breach -> wire into CI.
"""

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.agents import nodes
from app.agents.state import new_state
from app.core.logging import configure_logging, get_logger
from app.db.models import (
    Chunk, Citation, ClaimEvidence, Project, Report, Run,
)
from app.db.session import init_db, session_scope
from app.ingestion.pipeline import ingest_text_document
from app.stores.qdrant_store import ensure_collection

logger = get_logger("report-evals")


async def _seed(golden: dict) -> tuple[str, str, set[str]]:
    """Create a project, ingest the golden corpus, create a Run row. Returns
    (project_id, run_id, corpus_document_ids)."""
    async with session_scope() as session:
        project = Project(owner_id="evals", name="__report_golden__")
        session.add(project)
        await session.flush()
        pid = project.id
        doc_ids: set[str] = set()
        for doc in golden["corpus"]:
            row = await ingest_text_document(
                session, project_id=pid, text=f"# {doc['title']}\n\n{doc['text']}",
                source_type="paper", title=doc["title"], external_id=doc["doc_id"],
            )
            doc_ids.add(row.id)
        run = Run(project_id=pid, query=golden["query"], status="running")
        session.add(run)
        await session.flush()
        rid = run.id
    return pid, rid, doc_ids


def _build_state(golden: dict, project_id: str, run_id: str):
    state = new_state(run_id, project_id, golden["query"])
    state["clarification"] = {
        "objective": golden["objective"], "field": golden["field"],
        "domain": golden["field"],
        "sub_questions": [s["sub_question"] for s in golden["sections"]],
    }
    state["outline_title"] = "Verification and retrieval for grounded generation"
    state["paper_doc_ids"] = []  # not used by drafting; retrieval reads the DB corpus
    state["sections"] = [
        {"heading": s["heading"], "sub_question": s["sub_question"],
         "guidance": s["guidance"], "status": "pending", "claim_ids": [],
         "gap_note": "", "regens_used": 0, "track": "academic"}
        for s in golden["sections"]
    ]
    return state


async def run() -> int:
    configure_logging("WARNING", "console")
    await init_db()
    await ensure_collection()
    golden = json.loads(
        (Path(__file__).parent / "report_golden.json").read_text("utf-8"))
    answerable = {s["sub_question"]: s["answerable"] for s in golden["sections"]}

    project_id, run_id, corpus_doc_ids = await _seed(golden)
    state = _build_state(golden, project_id, run_id)

    # Drive the real grounding-critical path. draft_sections may schedule a
    # replan for unmet sub-questions; for a bounded eval we run one drafting pass
    # then assemble whatever verified (the unanswerable section stays a gap).
    await nodes.draft_sections_node(state)
    await nodes.assemble_node(state)

    report_id = state.get("report_id")
    if not report_id:
        print("FAIL: assemble produced no report")
        return 1

    # ── Audit the assembled report straight from the system of record ─────────
    fabricated_evidence = 0
    contradicted = 0
    cross_corpus = 0
    answered_answerable = 0
    total_answerable = 0
    gap_dishonest = 0
    shipped_claims = 0

    async with session_scope() as session:
        report = await session.get(Report, report_id)
        for section in report.sections:
            is_answerable = answerable.get(section["sub_question"], True)
            claim_ids = section.get("claim_ids", [])
            if is_answerable:
                total_answerable += 1
                if section["status"] == "verified" and claim_ids:
                    answered_answerable += 1
            else:
                # Unanswerable: MUST be a labeled gap with no shipped claims.
                if section["status"] != "gap" or claim_ids:
                    gap_dishonest += 1

            for cid in claim_ids:
                shipped_claims += 1
                evs = (await session.scalars(
                    select(ClaimEvidence).where(ClaimEvidence.claim_id == cid))).all()
                if not evs:
                    fabricated_evidence += 1
                    continue
                for ev in evs:
                    # quote must have matched an actual chunk span
                    if ev.quote_char_start < 0 or not ev.quote_match_ok:
                        fabricated_evidence += 1
                    if ev.nli_label == "contradiction":
                        contradicted += 1
                    # chunk must belong to THIS project's corpus (closed corpus)
                    chunk = await session.get(Chunk, ev.chunk_id)
                    if chunk is None or chunk.document_id not in corpus_doc_ids \
                            or chunk.project_id != project_id:
                        cross_corpus += 1

        # No Citation may point outside the seeded corpus.
        cites = (await session.scalars(
            select(Citation).where(Citation.project_id == project_id))).all()
        citation_leak = sum(
            1 for c in cites if c.document_id and c.document_id not in corpus_doc_ids)

    answered_rate = (answered_answerable / total_answerable) if total_answerable else 0.0
    results = {
        "shipped_claims": shipped_claims,
        "fabricated_evidence": fabricated_evidence,
        "cross_corpus_evidence": cross_corpus,
        "citation_leak": citation_leak,
        "nli_contradicted_claims": contradicted,
        "gap_dishonest_sections": gap_dishonest,
        "answered_rate": round(answered_rate, 3),
        "final_status": state.get("final_status"),
    }
    print("\n=== REPORT-PIPELINE EVAL RESULTS ===")
    print(json.dumps(results, indent=2))

    failures = []
    if fabricated_evidence > 0:
        failures.append(f"fabricated_evidence={fabricated_evidence} (must be 0)")
    if cross_corpus > 0:
        failures.append(f"cross_corpus_evidence={cross_corpus} (closed-corpus breach)")
    if citation_leak > 0:
        failures.append(f"citation_leak={citation_leak} (must be 0)")
    if contradicted > 0:
        failures.append(f"nli_contradicted_claims={contradicted} (must be 0)")
    if gap_dishonest > 0:
        failures.append(f"gap_dishonest_sections={gap_dishonest} (unanswerable not gap-labeled)")
    if total_answerable and answered_rate < 0.8:
        failures.append(f"answered_rate {answered_rate:.2f} < 0.80")

    if failures:
        print("\nRELEASE GATES FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\nAll report-pipeline gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
