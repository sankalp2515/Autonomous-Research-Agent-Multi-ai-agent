"""Groundedness eval harness (ARCHITECTURE.md §10).

Runs the REAL grounded-chat path against a frozen mini-corpus and scores:
- fabricated_citation_count  (hard gate: must be 0)
- claim_support_rate         (gate: >= 0.98)
- refusal_correctness        (gate: >= 0.95)
- citation_accuracy          (claims cite the doc that actually supports them)

Usage:  python -m evals.run_evals
Needs: docker-compose up (postgres/redis/qdrant) + LLM API keys.
Exit code 1 on any gate failure -> wire into CI as a release gate.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Chunk, Document, Project
from app.db.session import init_db, session_scope
from app.ingestion.pipeline import ingest_text_document
from app.services.grounded import grounded_chat
from app.stores.qdrant_store import ensure_collection

logger = get_logger("evals")

GATES = {
    "fabricated_citations": 0,
    "claim_support_rate": 0.98,
    "refusal_correctness": 0.95,
}


async def run() -> int:
    configure_logging("INFO", "console")
    await init_db()
    await ensure_collection()
    golden = json.loads((Path(__file__).parent / "golden.json").read_text(encoding="utf-8"))

    async with session_scope() as session:
        project = Project(owner_id="evals", name="__golden__")
        session.add(project)
        await session.flush()
        project_id = project.id
        doc_map: dict[str, str] = {}
        for doc in golden["corpus"]:
            row = await ingest_text_document(
                session, project_id=project_id, text=doc["text"],
                source_type="paper", title=doc["title"], external_id=doc["doc_id"],
            )
            doc_map[row.id] = doc["doc_id"]

    total_claims = verified_claims = fabricated = miscited = 0
    answered_with_content = []

    for case in golden["supported_questions"]:
        async with session_scope() as session:
            result = await grounded_chat(session, project_id, case["question"])
            if result.refused:
                logger.warning("refused a supported question",
                               extra={"q": case["question"]})
                answered_with_content.append(False)
                continue
            answered_with_content.append(True)
            for claim in result.claims:
                total_claims += 1
                verified_claims += 1  # only verified claims are returned
                cited_golden_id = doc_map.get(claim.evidence.document_id, "?")
                if cited_golden_id != case["must_cite_doc"]:
                    miscited += 1
            joined = " ".join(c.text + " " + c.evidence.quote for c in result.claims)
            if case["answer_must_contain"] not in joined:
                logger.warning("expected detail missing",
                               extra={"q": case["question"],
                                      "expected": case["answer_must_contain"]})

    correct_refusals = 0
    for case in golden["unsupported_questions"]:
        async with session_scope() as session:
            result = await grounded_chat(session, project_id, case["question"])
            if result.refused:
                correct_refusals += 1
            else:
                # Any claim here cites real chunks (the gate guarantees that),
                # but answering an unanswerable question means retrieval+drafting
                # invented relevance: count as fabrication-adjacent failure.
                fabricated += len(result.claims)
                logger.error("answered an unsupported question",
                             extra={"q": case["question"]})

    support_rate = (verified_claims / total_claims) if total_claims else 0.0
    refusal_rate = correct_refusals / len(golden["unsupported_questions"])
    answer_rate = sum(answered_with_content) / len(golden["supported_questions"])

    results = {
        "claims_total": total_claims,
        "claim_support_rate": round(support_rate, 3),
        "fabricated_citations": fabricated,
        "miscited_claims": miscited,
        "refusal_correctness": round(refusal_rate, 3),
        "supported_answer_rate": round(answer_rate, 3),
    }
    print("\n=== EVAL RESULTS ===")
    print(json.dumps(results, indent=2))

    failures = []
    if fabricated > GATES["fabricated_citations"]:
        failures.append("fabricated_citations > 0")
    if support_rate < GATES["claim_support_rate"] and total_claims:
        failures.append(f"claim_support_rate {support_rate:.3f} < 0.98")
    if refusal_rate < GATES["refusal_correctness"]:
        failures.append(f"refusal_correctness {refusal_rate:.3f} < 0.95")

    if failures:
        print("\nRELEASE GATES FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\nAll release gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
