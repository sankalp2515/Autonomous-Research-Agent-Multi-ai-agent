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


# ── Remote inference dispatch (Phase 2) ──────────────────────────────────────
# When settings.inference_service_url is set, calls go over HTTP to a dedicated
# model service (app/model_server.py) that can be scaled/replicated on its own.
# Otherwise the same computation runs in-process below. Callers are unchanged.

# The remote tier is ONE serialized process (see `_infer_lock`, which lives on
# the server). `_infer_lock` above protects only the IN-PROCESS path — the HTTP
# path had no bound at all, so ingest fired an unbounded fan of concurrent
# embeds at a service that can only run one at a time. They did not fail fast;
# they queued server-side, and every request's wall clock included the whole
# queue ahead of it, so the slowest ones crossed `inference_service_timeout` and
# were discarded as ReadTimeouts. On one real run that lost 73% of a project's
# chunk embeddings.
#
# Queueing in the CLIENT instead makes the wait explicit and un-timed: a caller
# holds here until a slot is free, then gets the server's undivided attention
# for a request whose duration is its own work, not the backlog's.
_remote_sem: "asyncio.Semaphore | None" = None
_remote_sem_loop = None


def _get_remote_sem() -> "asyncio.Semaphore":
    # Bound to the running loop: a module-level Semaphore created under a
    # different loop (worker vs API vs tests) raises when awaited.
    global _remote_sem, _remote_sem_loop
    loop = asyncio.get_running_loop()
    if _remote_sem is None or _remote_sem_loop is not loop:
        _remote_sem = asyncio.Semaphore(
            max(1, get_settings().inference_max_concurrency))
        _remote_sem_loop = loop
    return _remote_sem


async def _remote(path: str, payload: dict):
    import httpx
    settings = get_settings()
    url = settings.inference_service_url.rstrip("/") + path
    async with _get_remote_sem():
        async with httpx.AsyncClient(timeout=settings.inference_service_timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()


def _remote_enabled() -> bool:
    return bool(get_settings().inference_service_url)


def _local_embed(texts: list[str]) -> list[list[float]]:
    model = _embedder()
    if model is None:
        raise VerificationUnavailable("embeddings disabled (ML_EMBEDDINGS_ENABLED=false)")
    with _infer_lock:
        return model.encode(texts, normalize_embeddings=True, batch_size=32).tolist()


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if _remote_enabled():
        # BOUND THE REQUEST, NOT JUST THE QUEUE. A document's chunks were sent
        # as ONE call, so request duration scaled with paper length — and this
        # tier is CPU-only (measured: ~0.5s/chunk on the reference box, a 4-core
        # laptop). A 103-chunk paper is therefore a ~50s call, and a long one
        # crosses `inference_service_timeout` and is discarded WHOLE: every
        # chunk in that paper loses its vector even though the work was
        # progressing normally. That is how one run finished with 73% of its
        # chunks unembedded and retrieval silently degraded to BM25-only.
        #
        # Fixed-size slices make a call's duration independent of paper length,
        # so the timeout means "the tier is wedged" instead of "this paper was
        # long". A slow batch now costs one slice, not one document.
        size = max(1, get_settings().inference_embed_batch)
        if len(texts) <= size:
            return (await _remote("/embed", {"texts": texts}))["vectors"]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), size):
            part = texts[i : i + size]
            vectors.extend((await _remote("/embed", {"texts": part}))["vectors"])
        return vectors
    return await asyncio.to_thread(_local_embed, texts)


def _local_rerank(query: str, passages: list[str]) -> list[float]:
    model = _reranker()
    if model is None:
        return [0.0] * len(passages)  # rerank is an optimization; degrading is allowed
    with _infer_lock:
        return [float(s) for s in model.predict([(query, p) for p in passages])]


async def rerank(query: str, passages: list[str]) -> list[float]:
    if not passages:
        return []
    if _remote_enabled():
        return (await _remote("/rerank", {"query": query, "passages": passages}))["scores"]
    return await asyncio.to_thread(_local_rerank, query, passages)


async def nli_entailment(premise: str, hypothesis: str) -> tuple[str, float]:
    """Returns (label, score) where label in entailment|neutral|contradiction.
    NLI is a TRUTH layer: if disabled, callers must treat verification as
    unavailable rather than silently passing claims."""
    if _remote_enabled():
        data = await _remote("/nli", {"pairs": [[premise, hypothesis]]})
        r = data["results"][0]
        return (r[0], float(r[1]))
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
    # Remote FIRST. This used to call _nli() before the remote check, so a
    # worker running against the model tier (the whole point of which is not to
    # load 2GB of torch locally) took `model is None` and returned "skipped"
    # for every pair — silently downgrading the gate to quote-match only, on
    # the batch path the pipeline actually uses. The single-call variant below
    # already had this ordering right, which is why it never surfaced.
    if _remote_enabled():
        data = await _remote("/nli", {"pairs": [[p, h] for p, h in pairs]})
        return [(r[0], float(r[1])) for r in data["results"]]

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
