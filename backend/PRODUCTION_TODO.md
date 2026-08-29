# Veriscope Backend — Production-Readiness TODO

Derived from the backend audit (Phase 2 gap analysis + Phase 3 action list).
Ordered by the product's own priority rule:
**silently wrong/untrustworthy > breaks under usage > breaks under scale > polish.**

Legend — Severity: 🔴 Blocker · 🟠 Important · ⚪ Nice-to-have
Type: **[Fix now]** actionable directly · **[Decision]** needs a call from the owner first

---

## PHASE A — Trust core: could make verification silently wrong or unmeasured  ✅ DONE
> The product's value proposition lives here. Completed — see notes per item.

- [x] **A1** 🔴 [Fix now] **Fail closed when the NLI truth layer is unavailable in prod.** ✅
  Added `Settings.nli_required` (true when `app_env=prod`). `verify_claim`/`verify_claims` now raise `VerificationUnavailable` when NLI is required but off, OR on when the model isn't operational (returns "skipped"). Boot-time `assert_verification_ready()` wired into BOTH `main.create_app` and `worker.main`. Covered both silent holes (flag-off AND model-load-failure), in both processes.
  Files: `app/core/config.py` (nli_required), `app/verification/gate.py` (guards + assert), `app/main.py`, `app/worker.py`

- [~] **A2** 🔴 [Decision→resolved: extend bespoke] **Gate the REPORT pipeline + grow the eval set.** ✅ buildable parts done; ⏳ scale-up remains
  - Chat golden set grown 3→7 docs, 4→8 supported, 3→6 unsupported (`evals/golden.json`).
  - NEW report-pipeline harness `evals/run_report_evals.py`: seeds a fixed corpus and drives the real `draft_sections → assemble` path (research node is non-hermetic, so excluded), asserting fabricated_evidence==0, closed-corpus, no contradictions, honest gaps, answered_rate≥0.8. Golden: `evals/report_golden.json`.
  - Both wired into `.github/workflows/evals.yml`.
  - **Decision taken:** extend the bespoke harness (no new framework dep) — lower risk, reuses the real gate.
  - Eval sets grown: calibration 12→25 adversarial boundary cases (re-run: 0 FA / 0 FR, robust across all sweeps); chat golden 7 docs / 14 Qs; report golden 4 docs / 4 sections.
  - ⏳ **Remaining (larger effort):** grow to 50–100 cases with real-corpus + adversarial mix for a fully powered benchmark. Current sets are strong boundary/regression gates, not yet a statistical benchmark.

- [x] **A3** 🔴 [Decision→resolved] **Calibrate NLI + fuzzy-quote thresholds.** ✅ measured
  Promoted the hardcoded `0.85` strong-neutral bar to `nli_neutral_reject_threshold` (calibratable). Built `evals/calibrate.py` + labeled boundary set `evals/calibration_set.json`; ran it against the real DeBERTa NLI model: **0 false-accepts, 0 false-rejects across 12 boundary cases, robust across all swept thresholds.** Found + documented that `nli_entailment_threshold` (0.60) is **reserved/unenforced** — enforcing it would close no leak on this set. Written up in `docs/CALIBRATION.md` with the honest "boundary probe, not powered benchmark" caveat.
  ⏳ Re-run on the grown set from A2 before treating as fully data-backed.

- [x] **A4** 🔴 [Fix now] **Unit-test the gate decision logic.** ✅
  Audit correction: `tests/test_gate.py` already existed (deterministic layers). EXTENDED it with the NLI decision branch (entailment/contradiction/strong-neutral/mild-neutral via mocking — no torch needed), single-vs-batched agreement, and A1 fail-closed cases. 11→20 gate tests, all green.
  Files: `tests/test_gate.py`

---

## PHASE B — Breaks or misbehaves under real usage

- [x] **B1** 🟠 [Fix now] **Add a per-run lock on the run state machine.** ✅
  `acquire_run_lock`/`release_run_lock` (owner-token compare-and-delete, TTL = run_max_wall_seconds+300) in `redis_store.py`. `execute_run` acquires it and SKIPS if another worker holds it — closing the resume / orphan-recovery / active-worker double-execution race. Also added a terminal-status short-circuit so a stale re-enqueue of a finished run no-ops. Crashed-holder lock self-heals via TTL.
  Files: `app/agents/graph.py`, `app/stores/redis_store.py`

- [ ] **B2** 🟠 [Fix now] **Add resource limits (+ optional AV) to PDF ingestion.**
  Arbitrary PDFs parsed by PyMuPDF; only size + `%PDF` magic checked. A crafted PDF can OOM / pin CPU (decompression bomb). Add page-count and parse-timeout caps; treat uploads as hostile.
  Files: `app/ingestion/pdf_parser.py`, `app/ingestion/pipeline.py:62`, `app/api/routes.py:97`

- [x] **B3** 🟠 [Fix now] **Consolidate the two overlapping rate-limit middlewares.** ✅
  Removed the `main.py` limiter; kept the superior per-subject one in `observability.py` and made it read `settings.rate_limit_per_min` (was a hardcoded `RATE_LIMIT_PER_MIN=150`, now deleted) so config is authoritative. One limiter, one Redis key scheme.
  Files: `app/main.py`, `app/core/observability.py`

- [ ] **B4** 🟠 [Fix now] **Token/cost budgeting + per-project daily quota; input-token guard before send.**
  Budgets are enforced in call-count + wall-seconds only, never tokens/$. No per-user/project quota. No token estimate before LLM send → silent provider-side truncation on big sections (context-overflow gap). Required before routing any paid model.
  Files: `app/agents/state.py` (budget_left), `app/llm/router.py`, `app/agents/nodes.py:620` (_format_sources), `app/core/config.py:139-143`

- [ ] **B5** 🟠 [Decision] **Task-based quality routing to paid models.**
  `ROUTING` leads with free Gemini/Groq for everything incl. high-complexity drafting; report quality ceiling is bounded by free-tier drafting. Add a dial to spend more for a better report.
  **Decision needed:** which paid model for `draft`/`chat`, and the cost/quality trade-off.
  Files: `app/llm/router.py:47-67`

---

## PHASE C — Breaks under scale

- [x] **C1** 🟠 [Fix now] **Add pagination to all list endpoints.** ✅
  Bounded `limit`/`offset` (default 100, max 500) on projects, documents, runs, notes, memory, comparisons, notebook. Defaults chosen so existing single-page clients are unaffected while an unbounded full-table scan is capped. ⏳ frontend follow-up: adopt paging controls (noted in docs/SCALING.md).
  Files: `app/api/routes.py`

- [x] **C2** 🟠 [Fix now] **Fix the `notebook_list` N+1.** ✅
  Rewritten to batch-load claims + evidence + chunks + documents in a handful of queries (same shape as the report payload). Also paginated.
  Files: `app/api/routes.py`

- [x] **C3** 🟠 [Decision→documented] **Plan for the single global inference-lock bottleneck.** ✅
  Written up in `docs/SCALING.md`: near-term = scale workers horizontally (each process has its own lock; the B1 per-run lock makes it safe; needs `BLOB_BACKEND=s3`); medium-term = split inference into its own (GPU) service so torch + the lock leave the worker and inference batches across callers. Explicit warning NOT to remove the lock in-process (segfault). **Decision:** horizontal workers now, inference service when one worker saturates.
  Files: `docs/SCALING.md`, `app/ml/local_models.py` (unchanged — correct as is)

---

## PHASE D — Polish / hardening

- [x] **D1** ⚪ [Fix now] Make `ruff` a hard CI gate. ✅
  Removed `|| true`; now `ruff check app evals`. Fixed the 12 pre-existing/new lint errors (unused imports, an `OrderedDict` forward-ref, semicolon statements in `mapping.py`). Tree is clean.
  Files: `.github/workflows/ci.yml`, `app/retrieval/hybrid.py`, `app/services/mapping.py`, eval files

- [x] **D2** ⚪ [Fix now] Idempotency key on `POST /pipeline`. ✅
  Optional `Idempotency-Key` header, scoped by user+project, checked before backpressure and stored → run_id in Redis (24h). A retried submit returns the same run (`idempotent: true`) instead of launching a second.
  Files: `app/api/routes.py`, `app/stores/redis_store.py`

- [x] **D3** ⚪ [Fix now] `complete_json` repair now fails over to a DIFFERENT provider. ✅
  Added `exclude` to `complete`; the repair excludes the provider that just emitted unparseable JSON (falls back to the full chain if excluding leaves nothing). Outage failover was already present; this adds up-but-bad-at-JSON failover.
  Files: `app/llm/router.py`

- [x] **D4** ⚪ [Nice] Prometheus alert rules. ✅
  `deploy/observability/alerts.yml` (API down, 5xx rate, p99 latency, LLM error rate, all-LLM-failing, **gate verified-fraction collapse** = the trust signal, ingest quarantine rate, slow pipeline node). Wired via `rule_files` + compose mount. Note: worker liveness is log-based (no metrics endpoint) — alert via Loki.
  Files: `deploy/observability/alerts.yml`, `deploy/observability/prometheus.yml`, `docker-compose.observability.yml`

- [x] **D5** ⚪ [Nice] Rollback runbook. ✅
  `docs/RUNBOOK.md`: environment guards, expand-only migration rule, app-rollback-decoupled-from-schema procedure, restart/recovery behavior, post-deploy health checklist.
  Files: `docs/RUNBOOK.md`

- [x] **D6** ⚪ [Nice] Chunking roadmap decision. ✅
  Documented in `docs/SCALING.md`: keep fixed-size for v1 (provenance simplicity > marginal recall); evaluate semantic/late chunking and small-chunk+parent-expansion **with the report eval harness** before changing; revisit only if `context_recall` shows missed evidence.
  Files: `docs/SCALING.md`

---

### Notes / non-issues confirmed during audit (do NOT re-open)
- `.env` is gitignored and untracked ✔
- Alembic baseline (`0001_baseline.py`) covers all tables via `create_all(checkfirst=True)`; the "no migration" code comments are stale but harmless ✔
- IDOR checks (`_get_project`) present on every object-level route ✔
- Prompt-injection regex is bypassable but is defense-in-depth; the gate is the real backstop ✔
