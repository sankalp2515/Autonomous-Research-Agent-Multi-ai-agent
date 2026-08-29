"""RAGAS second-opinion eval (audit item #1).

Our bespoke gate-derived metrics (evals/run_evals.py, services/evaluation.py) are
the PRIMARY release gate. This adds RAGAS as an INDEPENDENT cross-check on the
same frozen golden set, so a regression the bespoke metrics miss still shows up,
and so we can say "we run RAGAS" with real numbers.

Deliberately OFFLINE only — RAGAS is LLM-judge-backed (cost + latency), so it
never touches the request path. It runs the real grounded-chat path, then scores
faithfulness / answer-relevancy / context-precision / context-recall.

RAGAS defaults to OpenAI; we don't use it — so we wire RAGAS to a free-tier
OpenAI-compatible provider (Groq) as the judge LLM and the LOCAL BGE model as the
embeddings, matching what the app itself uses.

Install:  pip install -e ".[ml,ragas]"
Run:      GROQ_API_KEY=... python -m evals.run_ragas
Needs:    docker-compose up (postgres/redis/qdrant), same as run_evals.py.
Informational (soft gate): prints scores; exits 0 unless a score falls below a
loose floor, so a flaky judge never blocks a release.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Project
from app.db.session import init_db, session_scope
from app.ingestion.pipeline import ingest_text_document
from app.services.grounded import grounded_chat
from app.stores.qdrant_store import ensure_collection

logger = get_logger("ragas")

# Loose floors — RAGAS uses an LLM judge, so treat these as smoke thresholds, not
# the hard gate (run_evals.py owns that).
FLOORS = {"faithfulness": 0.70, "answer_relevancy": 0.60}


def _build_ragas():
    """Wire RAGAS to Groq (judge) + local BGE (embeddings). Returns
    (evaluate, dataset_cls, metrics, llm, embeddings) or None with guidance."""
    settings = get_settings()
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_openai import ChatOpenAI
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import (
            Faithfulness, LLMContextPrecisionWithReference,
            LLMContextRecall, ResponseRelevancy,
        )
    except ImportError as exc:
        print(f"RAGAS not installed ({exc}).\n"
              "Install: pip install -e \".[ml,ragas]\"", file=sys.stderr)
        return None
    if not settings.groq_api_key:
        print("GROQ_API_KEY required (RAGAS judge LLM).", file=sys.stderr)
        return None

    judge = LangchainLLMWrapper(ChatOpenAI(
        model=settings.groq_model, temperature=0.0,
        base_url="https://api.groq.com/openai/v1", api_key=settings.groq_api_key))
    emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=settings.embedding_model))
    metrics = [Faithfulness(), ResponseRelevancy(),
               LLMContextPrecisionWithReference(), LLMContextRecall()]
    return evaluate, EvaluationDataset, metrics, judge, emb


async def _collect_samples(project_id: str, golden: dict) -> list[dict]:
    """Run the REAL grounded path for each supported question and shape a RAGAS
    sample: the question, our answer, the cited contexts, and the reference."""
    samples = []
    for case in golden["supported_questions"]:
        async with session_scope() as session:
            result = await grounded_chat(session, project_id, case["question"])
        d = result.as_dict()
        if d.get("refused") or not d.get("claims"):
            logger.warning("refused a supported question; skipping in RAGAS set",
                           extra={"q": case["question"]})
            continue
        answer = " ".join(c["text"] for c in d["claims"])
        # Cited evidence spans are our "retrieved contexts" (what actually grounded
        # the answer). Prefer the fuller chunk text when present, else the quote.
        contexts = []
        for c in d["claims"]:
            ev = c.get("evidence") or {}
            ctx = ev.get("chunk_text") or ev.get("quote")
            if ctx:
                contexts.append(ctx)
        samples.append({
            "user_input": case["question"],
            "response": answer,
            "retrieved_contexts": contexts or ["(no context)"],
            "reference": case.get("answer_must_contain", answer),
        })
    return samples


async def run() -> int:
    configure_logging("WARNING", "console")
    built = _build_ragas()
    if built is None:
        return 2
    evaluate, EvaluationDataset, metrics, judge, emb = built

    await init_db()
    await ensure_collection()
    golden = json.loads((Path(__file__).parent / "golden.json").read_text("utf-8"))

    async with session_scope() as session:
        project = Project(owner_id="evals", name="__ragas_golden__")
        session.add(project)
        await session.flush()
        project_id = project.id
        for doc in golden["corpus"]:
            await ingest_text_document(
                session, project_id=project_id, text=doc["text"],
                source_type="paper", title=doc["title"], external_id=doc["doc_id"])

    samples = await _collect_samples(project_id, golden)
    if not samples:
        print("No answerable samples produced — cannot run RAGAS.", file=sys.stderr)
        return 1

    dataset = EvaluationDataset.from_list(samples)
    # RAGAS runs its own (blocking) judge calls; keep it off the event loop.
    result = await asyncio.to_thread(
        evaluate, dataset=dataset, metrics=metrics, llm=judge, embeddings=emb)

    scores = {k: round(float(v), 3) for k, v in result.to_pandas().mean(numeric_only=True).items()}
    print("\n=== RAGAS RESULTS (second opinion) ===")
    print(json.dumps(scores, indent=2))

    failures = [f"{m} {scores[m]:.3f} < {floor}"
                for m, floor in FLOORS.items() if m in scores and scores[m] < floor]
    if failures:
        print("\nRAGAS soft floors breached (informational):")
        for f in failures:
            print(f"  ! {f}")
        return 1
    print("\nRAGAS soft floors passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
