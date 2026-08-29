"""Veriscope model server (Phase 2).

A dedicated inference service exposing embeddings, cross-encoder rerank, and NLI
entailment over HTTP. Running this as its OWN process/replica takes local ML off
the API's hot path: the API sets INFERENCE_SERVICE_URL to this server and calls
it over the network, so many API workers no longer serialize behind a single
in-process inference lock. The lock still lives HERE (torch thread-safety), but
this tier scales horizontally on its own (GPU nodes, more replicas) independent
of the API.

Run:  uvicorn app.model_server:app --host 0.0.0.0 --port 8100
The models are warmed EAGERLY at startup (see _guard_and_warm), so the first
real request does not pay a cold start that exceeds the client's timeout.
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.ml import local_models

logger = get_logger("model_server")

app = FastAPI(title="Veriscope Model Server", version="1.0.0")


def _pin_threads() -> int:
    """Bound torch's intra-op parallelism. THIS IS A CORRECTNESS FIX, NOT A TUNING KNOB.

    Torch defaults `num_threads` to the core count, and uvicorn dispatches each
    request into its own worker thread. Nothing bounded the product: PID 1 was
    observed with **73 threads pinning 1621% CPU on an 8-core host**, with a
    single 16-text embed still executing after ten minutes. Eight cores cannot
    run sixteen cores of work — past saturation the threads mostly evict each
    other's cache lines, so throughput collapses super-linearly rather than
    merely flattening.

    That collapse is what the ingest layer experienced as
    `httpcore.ReadTimeout`: on one real run it left **821 of 1130 chunks
    unembedded (73%)**, silently degrading retrieval to BM25-only — visible in
    the logs as "dimension dense retrieval unavailable; lexical only". The
    embeddings were not slow because the box was small; they were slow because
    we asked for more parallelism than the box has.

    All inference here is already serialized by `local_models._infer_lock`, so
    ONE operation runs at a time and can safely use the whole machine — but it
    must be told the machine's real size. Leaving one core for the event loop
    keeps health checks answerable while a batch is running.
    """
    import os

    import torch

    cores = os.cpu_count() or 4
    n = max(1, min(cores - 1, int(os.environ.get("INFERENCE_THREADS") or cores - 1)))
    torch.set_num_threads(n)
    # Interop (cross-op) parallelism on top of intra-op is what turns
    # oversubscription into thrashing; one is right for a serialized server.
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass  # already initialized — only settable before the first parallel op
    return n


@app.on_event("startup")
async def _guard_and_warm() -> None:
    # Guard against the one dangerous misconfiguration: if this server itself had
    # INFERENCE_SERVICE_URL set, it would proxy to itself forever. Refuse to boot.
    if get_settings().inference_service_url:
        raise RuntimeError(
            "the model server must run with INFERENCE_SERVICE_URL unset — it is "
            "the inference tier, not a client of one.")
    threads = _pin_threads()

    # WARM THE MODELS BEFORE ACCEPTING WORK. This hook has always been called
    # `_guard_and_warm` and the module docstring has always promised the models
    # load "eagerly at startup below" — but nothing here ever loaded them, so
    # they loaded lazily inside the FIRST request instead.
    #
    # That made the first request after every restart cost the whole cold start:
    # measured on this image, `import sentence_transformers` alone is 98s
    # (the pinned torch is a CUDA build, `2.13.0+cu130`, on a host with no GPU)
    # plus ~20s to load weights. Against `inference_service_timeout` of 120s the
    # first caller was therefore GUARANTEED to time out — and because a
    # ReadTimeout is indistinguishable from a wedged tier, the caller discarded
    # its work. It is exactly how a reindex of 821 chunks died at 123s having
    # embedded nothing, twice.
    #
    # Warming here moves that cost into startup, where the healthcheck already
    # waits for it and no request is pending. Failures are logged, not raised:
    # a model that cannot warm will fail loudly on first use with a real error,
    # which is more useful than refusing to boot the whole tier.
    settings = get_settings()
    for name, enabled, warm in (
        ("embeddings", settings.ml_embeddings_enabled,
         lambda: local_models.embed_texts(["warmup"])),
        ("rerank", settings.ml_rerank_enabled,
         lambda: local_models.rerank("warmup", ["warmup passage"])),
        ("nli", settings.ml_nli_enabled,
         lambda: local_models.nli_entailment("a warmup premise", "a warmup hypothesis")),
    ):
        if not enabled:
            continue
        try:
            import time as _time
            t0 = _time.perf_counter()
            await warm()
            logger.info("model warmed",
                        extra={"model": name, "seconds": round(_time.perf_counter() - t0, 1)})
        except Exception:
            logger.exception("model failed to warm; it will load on first use",
                             extra={"model": name})

    logger.info("model server ready", extra={"torch_threads": threads})


class EmbedReq(BaseModel):
    texts: list[str] = Field(max_length=512)


class RerankReq(BaseModel):
    query: str
    passages: list[str] = Field(max_length=256)


class NliReq(BaseModel):
    pairs: list[list[str]] = Field(max_length=256)  # [[premise, hypothesis], ...]


@app.post("/embed")
async def embed(req: EmbedReq):
    return {"vectors": await local_models.embed_texts(req.texts)}


@app.post("/rerank")
async def rerank(req: RerankReq):
    return {"scores": await local_models.rerank(req.query, req.passages)}


@app.post("/nli")
async def nli(req: NliReq):
    pairs = [(p[0], p[1]) for p in req.pairs if len(p) == 2]
    results = await local_models.nli_entailment_batch(pairs)
    return {"results": [[label, score] for label, score in results]}


@app.get("/health")
async def health():
    s = get_settings()
    return {"status": "ok",
            "embeddings": s.ml_embeddings_enabled,
            "rerank": s.ml_rerank_enabled,
            "nli": s.ml_nli_enabled}
