# VERISCOPE — STRONG / SAFE / DO-NOT-CLAIM

The vocabulary control document. Read this last before an interview.

---

## A. STRONG AREAS — steer here, you have hard evidence

These have code, tests, recorded measurements, or a written decision with a reason.

### A1. The verification gate (your single strongest asset)
Four ordered layers, exact thresholds, batched NLI, fail-closed in prod,
re-attribution rule, published refusals. Files: `verification/gate.py`,
`quote_match.py`. Tests: `test_gate.py`, `test_quote_match.py`,
`test_quote_match_markdown.py`, `test_gate_reattribution.py`,
`test_entity_guard_boundaries.py`, `test_verification_appendix.py`.
**Killer detail:** `nli_entailment_threshold = 0.60` exists but is **deliberately
not enforced**, and you can say exactly why (calibration showed enforcing it would
catch 0 additional false-accepts and add false-reject risk).

### A2. Quote-match as an engineering trick
"A weak model can hallucinate a paraphrase, but it cannot fake a quote that
survives normalized exact matching." Plus the hard-won details: NFKC, ligatures,
PDF hyphenated line-breaks, markdown table scaffolding, the underscore rule that
protects `snake_case`, and the ≥12-char minimum because shorter quotes are
unfalsifiable.

### A3. Hybrid retrieval, with the reasoning
BM25 (multi-query) + dense (query + HyDE + variants) → RRF(k=60) → cross-encoder
rerank → citation/recency priors → per-document diversity cap. Plus the strict
role separation: **cross-encoder scores relevance, NLI scores truth, never
swapped** — with the concrete reason ("X improves Y" vs "X does NOT improve Y"
score near-identically).

### A4. Dimension-directed retrieval — your best measured improvement
36.7% → 86.7% recall on missed matrix cells, measured by `evals/evidence_bench.py`.
And the honest follow-through: end-to-end matrix recall only reached **31.9%**, so
the fix was retrieval *and then* prompt grouping. This shows measurement discipline,
not just a win.

### A5. Contextual retrieval, done deterministically
Each chunk embedded and BM25-indexed as `"{title} — {section}\n{text}"` while the
**original text is stored for quote-matching** — the zero-LLM-cost version of the
technique, and it does not break the gate.

### A6. The Torch segfault debugging story
No traceback, process vanished, not OOM (15 GB free) → native crash → concurrent
`model.encode()` on a shared model from multiple threads → single inference lock +
bounded ingest concurrency. Verified by reproducing 24 concurrent embed+NLI calls.

### A7. Reliability engineering under free-tier constraints
Token buckets in **Lua** for atomicity, provider chain with instant throttle
failover, **circuit breaker** on hard statuses (401/402/403/404, 300s), 150s
per-call timeout, retry budget deliberately sized to **fit inside** that ceiling
(65+10+65=140s), prompt-hash response cache, JSON repair on a *different* provider.

### A8. Crash-safety and correctness of the run state machine
Per-node checkpoints, orphan recovery leader-gated by a Redis lock, per-run lock
with **owner token + heartbeat** (and why a run-length TTL was wrong), atomic
`LMOVE` claim (and why `BLMOVE` killed the worker on an idle queue), DLQ after 3
attempts, budget **rebasing** on resume.

### A9. Failure stories where the system lied, and the fix
- **D-33**: "5/5 sections verified · low_confidence: false" with four empty
  sections, caused by `gather(return_exceptions=True)` — fixed twice over (record
  the failure *and* invert the grounded test so unknown states are ungrounded by
  construction).
- The **237/237 rejected → report cited 12 papers it never acquired** incident →
  run-level refusal.
- **D-21**: a resumed run reported 22 unread papers as an evidence gap.
These are your best "I care about being wrong in the right direction" material.

### A10. Absence of evidence ≠ evidence of absence (the four cell states)
`reported` / `not_reported` / `not_applicable` (about the study) vs
`extraction_uncertain` (about **us**), with `not_reported` requiring evidence of
search **and** a second witness. And the corollary: **fill rate is not the
objective** — `evidence_bench` reports `mislabeled_not_reported` alongside fill
rate so trading honesty for completeness shows up as a regression.

### A11. The sentence-type system (E / D / S / I)
Especially: **D is safe because there is no LLM in its path** — it is reproducible
by recomputation, which is a harder guarantee than entailment. And **I is designed,
gated, and deliberately not shipped.**

### A12. Threshold calibration with an honest caveat
25 labeled boundary cases, 0 false-accepts / 0 false-rejects, robust across sweeps —
**and** "this is a boundary probe, not a statistically powered benchmark."

### A13. Measurement discipline as a practice (D-18)
"Two confident static diagnoses were wrong" — the arXiv query shape and the WS 403.
Both reverted because they were tested. And D-33's process note: *"four changes were
measured in ONE run, so the density drop could not be attributed to any of them —
change one thing per measured run."*

### A14. Backend/API engineering
Idempotency-Key on `POST /pipeline` (checked *before* backpressure), two-level
backpressure (503 shed + 409 per-project cap), per-subject rate limiting on hashed
token with streaming endpoints exempt, deep `/health`, Alembic as prod schema owner
with a CI job that applies migrations to a real Postgres and asserts a single head.

### A15. Product judgement with a kill criterion
D-32: the audio briefing is built only from gate-verified claims **and** carries an
explicit removal threshold ("under 5% press play in a month → remove it").
D-25: three renderers deleted because "the apparatus is the credibility of the
product and it is not the lede."

---

## B. SAFE AREAS — you understand these; answer conceptually, label the boundary

Say the implemented part first, then the conceptual part, and mark the seam.

| Topic | Implemented part you CAN claim | Where to switch to "how I'd approach it" |
|---|---|---|
| **Chunking strategy** | 1400-char section-aware chunks with page + char offsets as the provenance spine; tiny tails merged | Any claim of a **tuned** chunk size/overlap experiment. The overlap constant exists but is not applied, and `docs/SCALING.md` D6 says the decision was **keep fixed-size for v1** and evaluate semantic/late chunking **with the eval harness first**. |
| **Embedding model choice** | bge-small-en-v1.5, 384-dim, local CPU, free, no API limits | Any benchmark comparison you ran between embedding models — none exists in the repo |
| **Reranking evaluation** | rerank is implemented; `retrieval_eval.py` computes recall@k / MRR / nDCG@k | An **ablation** measuring rerank's contribution — not in the repo |
| **Human-in-the-loop** | interactive screening before any download; explicit selections get a higher cap | Anything about human review of *drafted claims* — not built |
| **Memory** | episodic + preference, per-project, embedding recall, walled off from evidence | TTL, supersede/invalidate, stale detection, sensitive-data handling, snapshotting — none built (see `VERISCOPE_SOURCE_OF_TRUTH.md` §7 for the safe conceptual answer) |
| **Scaling** | workers scale horizontally, atomic claim, stateless API, capped hot tier, `BLOB_BACKEND=s3` for multi-node, optional model tier | Any claim of running at scale or with concurrent users |
| **Observability** | full Prometheus/logs/traces stack + alert rules incl. gate-fraction collapse | Any claim of operating it in production or reading real dashboards under load |
| **Security** | JWKS RS256/ES256, HS256 rejected in prod, IDOR checks, security headers, injection screen, gitleaks + Trivy + npm audit in CI | Pentesting, a formal threat model, or SOC-type controls |
| **Cost** | per-run token accounting in Redis → `runs.budgets_spent`; free-tier by design | Any $ figure or cost-per-report number |
| **Contradiction detection** | two mechanisms (NLI over claim pairs; comparability-checked numeric disagreement) | Any claim that it surfaces contradictions **in practice** — D-23 records that they are empty on every report so far because no two papers shared a benchmark |
| **RAGAS** | wired as an offline, informational second opinion (Groq judge + local BGE) | Any RAGAS score value — none is recorded in the repo |
| **PDF safety** | size cap + magic check + quarantine | Decompression-bomb / AV protection — `PRODUCTION_TODO.md` B2 is **open** |

---

## C. DO NOT CLAIM — not supported by the sources

Saying any of these will not survive a follow-up.

### C1. Metrics you must never present as your results
- ❌ "RAG reduced factual errors by 37%", "RRF improved recall@10 by 18%",
  "88% at 256 tokens vs 64% at 1024", "quote-match drove fabricated citations to
  zero across 1,000 claims", "the entailment gate caught 96% of out-of-context
  quotations", "1,200 annotated pairs".
  **These are text inside the synthetic golden fixtures (`evals/golden.json`,
  `evals/report_golden.json`). They are eval INPUTS, not your findings.**
  This is the single highest-risk trap in this repo.
- ❌ Any measured value for `claim_support_rate`, `fabricated_citations`,
  `refusal_correctness` or `recall@10` from a real run. **These are release
  *thresholds* (0 / ≥0.98 / ≥0.95 / ≥0.90), not recorded results.** Correct phrasing:
  *"the harness enforces those as release gates."*
- ❌ Any RAGAS number, any p50/p95 API latency, any cost in dollars, any accuracy
  or F1 for the pipeline as a whole.

### C2. Technologies not used
- ❌ **Neo4j** or any graph database — explicitly rejected with reasoning.
- ❌ **Kafka / RabbitMQ / SQS / Celery** — the queue is a Redis LIST with a
  processing list and a DLQ.
- ❌ **Kubernetes / Terraform / AWS ECS** — deployment is Docker Compose over SSH.
  (`docs/aws-integration/demo.html` exists; it is a demo page, not an integration.)
- ❌ **Elasticsearch / OpenSearch / Postgres FTS / Qdrant sparse vectors** — lexical
  search is in-process `rank-bm25`. Postgres FTS is listed as a **deferred** idea.
- ❌ **Fine-tuning, LoRA, model training, RLHF, distillation** — nothing is trained.
- ❌ **OpenAI / Anthropic as a runtime provider** — the fleet is NVIDIA NIM, Groq,
  Gemini, DeepSeek, OpenRouter. (`langchain-openai` appears only as a RAGAS judge
  adapter pointed at Groq.)
- ❌ **GPU inference** — everything local is CPU (~0.5s/chunk measured on a 4-core
  laptop). A GPU model tier is a *medium-term* idea in `docs/SCALING.md`.
- ❌ **LangChain as the framework** — LangGraph is used; LangChain packages appear
  only in the optional RAGAS extra.
- ❌ **Streaming token-by-token LLM output** — progress streams over SSE/WebSocket;
  LLM calls are non-streaming.

### C3. Capabilities not built
- ❌ **LLM function-calling / dynamic tool selection / an autonomous agent loop.**
  Orchestration is deterministic Python; the LLM only fills validated schemas.
  Correct phrasing: *"deterministic orchestration with schema-constrained LLM steps."*
- ❌ **Sandboxing / generated-code execution** — the system never generates or runs
  code, so there is nothing to sandbox. Say that; it is a better answer than
  pretending.
- ❌ **OCR** for scanned PDFs — raises an honest error instead.
- ❌ **Token-budget or per-project $ quota, or an input-token guard before send** —
  `PRODUCTION_TODO.md` B4 is open.
- ❌ **Paid-model quality routing** — B5 is an open decision.
- ❌ **Semantic-memory writer, memory TTL/versioning/invalidation.**
- ❌ **Citation edges in the discovery Map by default** —
  `map_citation_edges_enabled = False`.
- ❌ **GitHub / engineering-blog sources in a normal run** —
  `practitioner_sources_enabled = False`. The code exists; the track is off.
- ❌ **Interpretive (I) sentences** — designed, gated, deliberately not emitted.
- ❌ **Real-time collaboration, multi-tenant hosted deployment** — deferred by decision.

### C4. Process / product claims not supported
- ❌ **User A/B tests, feature-flag experiments, staged rollouts, online evaluation
  on production traffic, real user interviews, retention or usage numbers, NPS.**
  The evidence base is ~55 **public complaints**; the only A/B is an **offline
  replay** of two extraction arms (`evals/extraction_ab.py`).
- ❌ **"Deployed in production" / "used by N researchers."** The CD job is
  self-disabling when `DEPLOY_HOST` is unset and "hosted demo" is still on the
  roadmap. Say **"deployment-ready, not deployed"** — CI/CD, images, migrations,
  health checks and a rollback runbook all exist.
- ❌ **Team scale / code review process / on-call.** This is a single-author repo
  (5 commits, one author). Talk about the *discipline* (decisions log, tests as
  pins, measure-before-diagnose), not about a team.
- ❌ **"Zero hallucinations in production"** — claim the structural property
  instead: *"a fabricated citation has no code path, because references render only
  from resolved `Citation` rows."*

### C5. Stale doc numbers to avoid repeating
- ❌ "7-node pipeline" → it is **9**.
- ❌ "32 unit tests" → **40 files / 355 tests**.
- ❌ "4-provider fleet" → **5 configured providers**.
- ❌ "60 LLM calls / 1800s budget" → **200 calls / 5400s**.
- ❌ "12 calibration cases" → **25**.
- ❌ "outline node" → **report_architect** (and D-22 short-circuits it).

---

## D. Three sentences that are always safe to say

1. *"Agents propose, deterministic verifiers dispose — LLMs are never the final
   authority on truth in this system."*
2. *"A weak model can hallucinate a paraphrase, but it cannot fake a quote that
   survives normalized exact matching against the cited chunk — that's what made
   free-tier models usable for this."*
3. *"An LLM judge may annotate quality, but it never gates truth."*

## E. One sentence that is always safe when you don't know

*"That one I designed but didn't build — let me tell you what's actually in the
repo and then how I'd extend it."*
