"""Local ML models: embeddings, cross-encoder rerank, NLI entailment.

All heavyweight imports are lazy and guarded by feature flags so the API,
unit tests, and pure-pipeline code run without torch installed. Each model
loads once per process and runs in a thread to keep the event loop free.

Roles are strict (the v1 lesson):
- cross-encoder scores RELEVANCE (reranking) - never truth.
- NLI scores ENTAILMENT (the gate's truth check).
"""

import asyncio
import base64
import hashlib
import json
import struct
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
    """Vectors for `texts`, memoized by content.

    Embedding is the largest single cost in ingest (measured: 20.4s of a 36.6s
    paper) and the tier is serialized, so re-ingesting a paper the system has
    already read — the same PDF entering a second project, a re-run of the same
    question — used to pay full price for byte-identical chunks."""
    if not texts:
        return []
    keys = [_memo_key("emb", t) for t in texts]
    cached = await _memo_get(keys)
    out: list[list[float] | None] = [None] * len(texts)
    todo: list[int] = []
    for i, raw in enumerate(cached):
        vec = _unpack_vector(raw)
        if vec is None:
            todo.append(i)
        else:
            out[i] = vec
    if todo:
        fresh = await _embed_texts_uncached([texts[i] for i in todo])
        # A length mismatch means the tier returned something we cannot align
        # to our inputs. Fall back wholesale rather than pair a chunk with
        # another chunk's vector, which would corrupt retrieval silently.
        if len(fresh) != len(todo):
            return await _embed_texts_uncached(texts)
        writes: dict[str, str] = {}
        for i, vec in zip(todo, fresh):
            out[i] = vec
            writes[keys[i]] = _pack_vector(vec)
        await _memo_set(writes)
    return [v if v is not None else [] for v in out]


async def _embed_texts_uncached(texts: list[str]) -> list[list[float]]:
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
    """Cross-encoder relevance scores, memoized by (query, passage).

    THE MEMO THIS TIER WAS MISSING. Embedding and NLI were memoized; rerank was
    not, and it sits on BOTH hot paths — `dimension.py` reranks candidates while
    extracting each paper, and `hybrid.py` reranks again while drafting each
    section. It is the same CPU-only, lock-serialized cross-encoder, so on a
    re-run of an identical corpus it was re-scoring identical (query, passage)
    pairs from scratch. Measured on a warm run of an already-read corpus:
    extraction 207s and drafting 178s, of which the model calls accounted for
    well under half — the remainder was this.

    Scored per PASSAGE rather than per batch, so a section that shares most of
    its candidates with a previous run pays only for the ones that are new."""
    if not passages:
        return []
    keys = [_memo_key("rrk", query, p) for p in passages]
    cached = await _memo_get(keys)
    out: list[float | None] = [None] * len(passages)
    todo: list[int] = []
    for i, raw in enumerate(cached):
        try:
            out[i] = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            out[i] = None
        if out[i] is None:
            todo.append(i)
    if todo:
        fresh = await _rerank_uncached(query, [passages[i] for i in todo])
        # A length mismatch means we cannot align scores to passages; fall back
        # wholesale rather than score a passage with another's number, which
        # would silently reorder retrieval.
        if len(fresh) != len(todo):
            return await _rerank_uncached(query, passages)
        writes: dict[str, str] = {}
        for i, score in zip(todo, fresh):
            out[i] = float(score)
            writes[keys[i]] = repr(float(score))
        await _memo_set(writes)
    return [0.0 if v is None else v for v in out]


async def _rerank_uncached(query: str, passages: list[str]) -> list[float]:
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


# ── Inference memo (content-addressed, Redis) ────────────────────────────
#
# Embedding and NLI are DETERMINISTIC in their inputs, and this tier is
# CPU-only and lock-serialized — on the reference box it is the single largest
# cost in a run (measured: ~35s for one paper's extraction gate, ~13s to embed
# 40 chunks). So results are memoized by CONTENT.
#
# This is not a shortcut around the gate. A cached verdict is the verdict that
# exact (premise, hypothesis) pair produced, and every claim is still scored
# before it can ship. What it buys is that a paper re-read in a SECOND project,
# or a claim re-verified after a replan, does not pay for the same forward pass
# twice.
#
# Deliberate: a "skipped" verdict is NEVER cached (it describes the process,
# not the pair — caching it would pin a degraded gate in place), and every read
# and write is best-effort, so a Redis outage costs speed and can never change
# a verdict or fail a run.

_MEMO_TTL = 60 * 60 * 24 * 30       # the key changes whenever the text does


def _memo_key(prefix: str, *parts: str) -> str:
    h = hashlib.sha256(("\x00".join(parts)).encode("utf-8", "replace")).hexdigest()
    return f"infmemo:{prefix}:{h}"


async def _memo_get(keys: list[str]) -> list[str | None]:
    if not keys:
        return []
    try:
        from app.stores.redis_store import get_redis
        return list(await get_redis().mget(keys))
    except Exception:
        return [None] * len(keys)


async def _memo_set(pairs: dict[str, str]) -> None:
    if not pairs:
        return
    try:
        from app.stores.redis_store import get_redis
        pipe = get_redis().pipeline()
        for k, v in pairs.items():
            pipe.set(k, v, ex=_MEMO_TTL)
        await pipe.execute()
    except Exception:
        pass


def _pack_vector(vec: list[float]) -> str:
    """base64 of float32: ~2KB per 384-dim vector against ~9KB as JSON. base64
    rather than raw bytes because the shared Redis client runs with
    decode_responses=True, and raw float32 is not valid UTF-8 — it would come
    back corrupted, which for a vector means silently WRONG retrieval rather
    than a visible error."""
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


def _unpack_vector(raw) -> list[float] | None:
    if not raw:
        return None
    try:
        blob = base64.b64decode(raw, validate=True)
        if not blob or len(blob) % 4:
            return None
        return list(struct.unpack(f"<{len(blob) // 4}f", blob))
    except Exception:
        return None


async def nli_entailment_batch(
    pairs: list[tuple[str, str]]
) -> list[tuple[str, float]]:
    """Batched entailment: one forward pass (one lock acquisition) for many
    (premise, hypothesis) pairs, instead of N serialized single calls. The
    verification gate scores a whole section's claims at once through here —
    the single biggest inference-throughput win on the hot path.

    Verdicts are memoized by content (see the memo block above): a pair already
    scored is not scored again, and only the unseen pairs reach the model."""
    if not pairs:
        return []

    keys = [_memo_key("nli", p, h) for p, h in pairs]
    cached = await _memo_get(keys)
    out: list[tuple[str, float] | None] = [None] * len(pairs)
    todo: list[int] = []
    for i, raw in enumerate(cached):
        if raw is None:
            todo.append(i)
            continue
        try:
            label, score = json.loads(raw)
            out[i] = (str(label), float(score))
        except Exception:
            todo.append(i)
    if todo:
        scored = await _nli_entailment_batch_uncached([pairs[i] for i in todo])
        if len(scored) != len(todo):
            return await _nli_entailment_batch_uncached(pairs)
        fresh: dict[str, str] = {}
        for i, verdict in zip(todo, scored):
            out[i] = verdict
            if verdict[0] != "skipped":
                fresh[keys[i]] = json.dumps([verdict[0], verdict[1]])
        await _memo_set(fresh)
    return [o if o is not None else ("skipped", 0.0) for o in out]


async def _nli_entailment_batch_uncached(
    pairs: list[tuple[str, str]]
) -> list[tuple[str, float]]:
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
