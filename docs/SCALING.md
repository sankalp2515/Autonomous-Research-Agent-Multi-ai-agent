# Scaling notes & known bottlenecks

What breaks first as load grows, and the intended path past each. Written as
part of the production-readiness pass (audit items C3, C1/C2, D6).

## 1. The global inference lock (C3) — the throughput ceiling

`app/ml/local_models.py` funnels **all** local model inference — embeddings,
cross-encoder rerank, and NLI entailment — through a single process-wide
`threading.Lock` (`_infer_lock`). This is **correct and deliberate**: torch
models are not safe to call concurrently on one instance (parallel `encode()`
segfaults the process with no Python traceback). But it means:

- Only one inference runs at a time per worker process, across every stage.
- Under load, ingestion (embedding) and verification (NLI) **contend on the same
  lock**. A run drafting sections waits behind another run's PDF embedding.
- It is the first thing to saturate under ~10x concurrent runs on one worker.

**Scaling path (in order of effort):**

1. **Scale workers horizontally first.** Each worker process has its own lock, so
   N workers give N-way inference parallelism. The per-run lock (B1) makes this
   safe — a run executes on exactly one worker. This is the near-term answer:
   run more worker replicas, each with the ML stack. Requires the shared blob
   backend (`BLOB_BACKEND=s3`) so replicas share the paper library.
2. **Split inference into its own service.** Move embeddings/rerank/NLI behind a
   dedicated inference service (e.g. a small FastAPI + a batching queue, or a
   Triton / TEI server) with its own GPU. The API/worker call it over HTTP. This
   removes torch (and its ~2GB memory + the lock) from the worker entirely and
   lets inference batch across all callers — the single biggest throughput win.
3. **GPU + true batching.** The gate already batches NLI per section
   (`nli_entailment_batch`); a GPU inference service extends that to cross-run
   batching, which is where the cost model improves the most.

**Do not** remove the lock to "parallelize" inference in-process — that
reintroduces the segfault. The lock goes away only by moving the models out of
the process (option 2).

## 2. List endpoints (C1) & N+1 (C2) — fixed

- All list endpoints (`projects`, `documents`, `runs`, `notes`, `memory`,
  `comparisons`, `notebook`) now take bounded `limit`/`offset` (default 100, max
  500) so a large project can no longer return an unbounded full-table scan.
  **Frontend follow-up:** adopt paging controls; today it relies on the default
  page being large enough.
- `notebook_list` was a per-row N+1 (claim + evidence + chunk + document each
  iteration); it now batch-loads in a handful of queries like the report payload.
- Remaining audit target: sweep other handlers for the same pattern as corpora
  grow (the report payload and notebook are done; watch `resume`, `map`).

## 3. Retrieval / chunking roadmap (D6) — decision deferred, not forgotten

Chunking is currently fixed-size (~1400 chars, 150 overlap, heading-tracked;
`app/ingestion/chunker.py`). It is sane for papers and keeps char-offset
provenance simple. Two v2 options, to be evaluated **with the report-pipeline
eval harness** (`evals/run_report_evals.py`) so any change is measured, not
guessed:

- **Semantic / late chunking** — chunk on embedding-similarity boundaries or
  embed the whole doc then pool per span. Can improve retrieval precision but
  complicates the char-offset → quote-match provenance that the gate depends on.
- **Small-chunk + parent-doc expansion** — retrieve small (precise citation
  spans) but hand the model the surrounding parent context. The golden set g5
  ("chunk size and grounding") already encodes the trade-off to measure.

**Decision:** keep fixed-size for v1 (provenance simplicity is worth more than a
marginal recall gain right now). Revisit only if the report eval's
`context_recall` shows retrieval missing evidence the corpus contains.

## Vector search (pgvector)

Vectors live on `chunks.embedding` (`vector(384)`). Every query is scoped to
one project or one document, and runs as an **exact** cosine scan with no ANN
index. A project of 28-100 papers is 2-6k chunks; the scan takes milliseconds
and never misses a neighbour, which an approximate index cannot promise.

Add an HNSW index only when one project passes roughly 100k chunks, and then:

- use pgvector >= 0.8 with `hnsw.iterative_scan = relaxed_order`, or a
  filtered query (`WHERE project_id = ...`) can return fewer rows than its
  LIMIT, because the filter runs after the index walk;
- measure with `evals.evidence_bench` before and after; the switch must not
  lower cell recall.

Per-paper extraction does not query the database per dimension: it fetches the
paper's ~60 vectors once and ranks every dimension query in memory
(`vector_store.rank_within_document`).
