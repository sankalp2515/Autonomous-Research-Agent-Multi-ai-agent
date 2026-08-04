"""Local ML models: embeddings, cross-encoder rerank, NLI entailment.

All heavyweight imports are lazy and guarded by feature flags so the API,
unit tests, and pure-pipeline code run without torch installed. Each model
loads once per process and runs in a thread to keep the event loop free.

Roles are strict (the v1 lesson):
- cross-encoder scores RELEVANCE (reranking) - never truth.
- NLI scores ENTAILMENT (the gate's truth check).
"""

import asyncio
import threading
from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import VerificationUnavailable
from app.core.logging import get_logger

logger = get_logger("ml")


@lru_cache(maxsize=1)
def _embedder():
    settings = get_settings()
    if not settings.ml_embeddings_enabled:
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.error("ML_EMBEDDINGS_ENABLED but sentence-transformers missing - "
                     "install backend extras: pip install .[ml]")
        return None
    logger.info("loading embedding model", extra={"model": settings.embedding_model})
    return SentenceTransformer(settings.embedding_model)


@lru_cache(maxsize=1)
def _reranker():
    settings = get_settings()
    if not settings.ml_rerank_enabled:
        return None
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        logger.error("ML_RERANK_ENABLED but sentence-transformers missing - "
                     "rerank degraded to RRF order")
        return None
    logger.info("loading rerank model", extra={"model": settings.rerank_model})
    return CrossEncoder(settings.rerank_model)


@lru_cache(maxsize=1)
def _nli():
    settings = get_settings()
    if not settings.ml_nli_enabled:
        return None
    try:
        from transformers import pipeline
    except ImportError:
        logger.error("ML_NLI_ENABLED but transformers missing - entailment "
                     "layer skipped; quote-match remains the hard gate")
        return None
    logger.info("loading nli model", extra={"model": settings.nli_model})
    return pipeline("text-classification", model=settings.nli_model, top_k=None)


# Torch/transformers models are NOT safe to call concurrently from multiple
# threads on the same instance - parallel encode() calls segfault the process
# (silent native crash, no Python traceback). All local inference is funneled
# through this single lock so only one thread touches a model at a time.
_infer_lock = threading.Lock()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    model = _embedder()
    if model is None:
        raise VerificationUnavailable("embeddings disabled (ML_EMBEDDINGS_ENABLED=false)")
    def _run():
        with _infer_lock:
            return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()
    return await asyncio.to_thread(_run)


async def rerank(query: str, passages: list[str]) -> list[float]:
    model = _reranker()
    if model is None:
        # Rerank is an optimization, not a guarantee: degrading is allowed.
        return [0.0] * len(passages)
    def _run():
        with _infer_lock:
            return [float(s) for s in model.predict([(query, p) for p in passages])]
    return await asyncio.to_thread(_run)


async def nli_entailment(premise: str, hypothesis: str) -> tuple[str, float]:
    """Returns (label, score) where label in entailment|neutral|contradiction.
    NLI is a TRUTH layer: if disabled, callers must treat verification as
    unavailable rather than silently passing claims."""
    model = _nli()
    if model is None:
        # Soft skip: quote exact-match (deterministic) is still enforced
        # upstream; entailment is the additional out-of-context check.
        return ("skipped", 0.0)
    def _run():
        with _infer_lock:
            rows = model({"text": premise[:2000], "text_pair": hypothesis[:1000]})
        scores = {r["label"].lower(): r["score"] for r in rows}
        label = max(scores, key=scores.get)
        return label, scores[label]
    return await asyncio.to_thread(_run)


async def nli_entailment_batch(
    pairs: list[tuple[str, str]]
) -> list[tuple[str, float]]:
    """Batched entailment: one forward pass (one lock acquisition) for many
    (premise, hypothesis) pairs, instead of N serialized single calls. The
    verification gate scores a whole section's claims at once through here —
    the single biggest inference-throughput win on the hot path."""
    if not pairs:
        return []
    model = _nli()
    if model is None:
        return [("skipped", 0.0)] * len(pairs)

    def _run():
        inputs = [{"text": p[:2000], "text_pair": h[:1000]} for p, h in pairs]
        with _infer_lock:
            batched = model(inputs, batch_size=16)
        out: list[tuple[str, float]] = []
        for rows in batched:
            scores = {r["label"].lower(): r["score"] for r in rows}
            label = max(scores, key=scores.get)
            out.append((label, scores[label]))
        return out
    return await asyncio.to_thread(_run)


def nli_available() -> bool:
    return get_settings().ml_nli_enabled
