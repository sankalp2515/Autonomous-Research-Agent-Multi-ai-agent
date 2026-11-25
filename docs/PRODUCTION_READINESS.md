# Production readiness register

**Question this answers:** if the infrastructure existed tomorrow, could we
deploy and let researchers use Veriscope? Every gap found in a full audit of
the backend, worker, web tier, containers, CI/CD and infrastructure is listed
here with its status. Nothing is listed as fixed without the file that fixes it
and the test that pins it.

Audit date: 2026-11-19. Target: Google Cloud project `veriscope-515119`
(`infra/gcp`). Related: [RUNBOOK.md](RUNBOOK.md) (operate), [SCALING.md](SCALING.md)
(grow), [infra/gcp/README.md](../infra/gcp/README.md) (provision).

**Verdict:** the code is deployable. **Launch is blocked on 11 items (section
2)**: one is billing, five need product or legal decisions, five are
engineering work. One of them (L10) is about what the product may CLAIM: the
verification gate's false-accept rate on an expert benchmark is too high to
advertise "verified" as a truth guarantee.

**2026-11-25 addendum — found by the research-synthesis benchmarks**
(docs/EVALUATION.md). Running the pipeline against human gold labels for the
first time surfaced five silently-wrong defects and one credential leak (F42-F47
below). None was visible to the unit suite, because each fake returned complete,
well-formed answers; a real provider does not.

---

## 1. Fixed in this pass

Ordered by the product's own rule: silently wrong > breaks under use > breaks
under scale > polish.

### Silently wrong (the worst class: the product looks fine and is not)

| # | Gap | Failure it caused | Fix | Pinned by |
|---|---|---|---|---|
| F1 | Chunk vectors lived in Qdrant, written separately from the chunk row | text and vector could drift; a Qdrant outage silently degraded every report to keyword-only retrieval while it read just as confident | vectors on `chunks.embedding` (pgvector), one transaction with the text; `app/stores/pgvector_store.py`, migration `0007` | `test_pgvector_store.py`, `test_pgvector_integration.py` (CI, real pgvector) |
| F2 | Dense-retrieval failure logged at `info` and nothing else | half of retrieval missing with no signal anywhere | counter `retrieval_dense_degraded_total` + alert `VeriscopeDenseRetrievalDegraded` | `test_pgvector_store.py::test_dense_failure_is_counted_not_silent` |
| F3 | Recovered runs lost the user's launch filters (scope, year window, citation floor, hand-picked papers) | a run orphaned before its first checkpoint resumed with defaults and answered a broader question than the user asked | `runs.launch_params` (migration `0008`), read by `execute_run` | migration CI step; `graph.py` fresh-state branch |
| F4 | Prometheus scraped only the API, but the gate and pipeline run in the worker | the trust alert (gate verifying < 30% of claims) never saw a single pipeline claim | worker `/metrics`; scrape target added | `deploy/observability/prometheus.yml` |
| F5 | Library reads/writes did blocking network I/O inside the event loop (GCS/S3) | a slow PDF read stalled the run-lock and job-lease heartbeats; a live run could look dead | `blob_store.a*` wrappers via `asyncio.to_thread` | all callers switched (`nodes.py`, `routes.py`, `import_lib.py`) |
| F42 | Gemini and Vertex clients read `parts[0]` of the answer only | Gemini splits one answer across parts with `finishReason=STOP` (measured: [4946, 37] chars); the tail was dropped at EVERY step using Gemini, the JSON stopped parsing and the repair rebuilt it from a fragment | `_gemini_answer_text` joins all non-thought parts; empty answer is an error; MAX_TOKENS logged | `test_secret_redaction.py::test_a_split_gemini_answer_is_joined`, `test_vertex_uses_the_same_parser` |
| F43 | Screening: a candidate the response returned NO verdict for was dropped and counted as "screened out" | on a published review (Hall 2012) 78 of 304 records were never assessed, 27 of them included studies; the PRISMA box called them screened out | verdicts filed per batch; unassessed papers re-screened once in smaller batches; still-unassessed = `screen_no_verdict`, own funnel count and a `--warn` PRISMA box | `test_screening_admission.py::test_a_candidate_with_no_verdict_is_rescreened`, `test_still_unassessed_papers_are_not_counted_as_screened_out` |
| F44 | Screening: a verdict whose index was not in its own batch was applied to the whole candidate list | a repaired response renumbered papers, so one call decided papers it never showed the model (4-11 per run) | a verdict counts only for an index its prompt carried; `screen_foreign_verdicts` counted | `test_a_verdict_for_an_index_outside_its_batch_is_ignored` |
| F45 | JSON repair echoed only the first 3,000 chars of the failed output | one malformed field in a 15-item list came back "repaired" as the items that fit: valid and silently incomplete | repair sees up to 24,000 chars and is told to keep every item; screen output cap 8,192 | `test_the_screen_asks_for_an_output_budget_that_fits_the_batch` |
| F46 | OpenAI-compatible providers: `null` content and `finish_reason=length` passed through | an empty or truncated answer reached the JSON parser as if it were a formatting error | empty answer raises (router fails over); truncation logged | `app/llm/clients.py` |

Net effect on screening recall against the reviewers' labels (all 104 included
studies, `evals/screening_bench.py`): **48.1% -> 91.3-92.3%** (two runs), with
no record left unassessed.

### Breaks under real use

| # | Gap | Failure | Fix | Pinned by |
|---|---|---|---|---|
| F6 | A run's job was enqueued BEFORE its row committed | a fast worker found no run, completed the job, and the run sat at `queued` forever | commit, then enqueue (`start_pipeline`, `resume`) | `routes.py` |
| F7 | Worker boot recovery `DEL`eted the queue and rebuilt it from Run rows | every restart silently dropped queued invite emails, BibTeX imports, reindex and monitor jobs | queue is never wiped; `maintenance()` reaps and reconciles | `test_job_queue.py::test_nothing_in_the_queue_is_ever_deleted_by_recovery` |
| F8 | A crashed worker's job stayed in `processing` until some worker restarted | with N healthy workers and one dead, its run never moved again | job leases (120s, renewed every 30s) + a reaper every 60s on any surviving worker | `test_job_queue.py` (10 tests on fakeredis with Lua) |
| F9 | A run that killed its worker could be re-enqueued forever | crash loop across the fleet | after 3 attempts -> dead-letter queue, run marked `failed` with a reason | `test_job_queue.py::test_a_job_that_keeps_killing_its_worker...` |
| F10 | SIGTERM only stopped the loop; the in-flight job was killed with the container | lost work on every deploy and scale-in | 8s grace, then the job is handed back without counting an attempt | `worker.py::_run_with_lease`, `test_failures_count_attempts_but_shutdowns_do_not` |
| F11 | Web tier: nginx's default 1 MB body limit | every PDF upload over 1 MB through the web origin failed with 413 | `client_max_body_size 31m` | `frontend/nginx.conf` |
| F12 | Upload limit 50 MB, but Cloud Run's front end rejects HTTP/1.1 bodies over 32 MiB | the UI promised uploads the platform refuses | `upload_max_pdf_mb = 30` (server-side fetches keep 50) | `config.py` |
| F13 | Multipart uploads were spooled in full before the handler's size check | a large POST filled `/tmp`, which is memory on Cloud Run: an OOM vector | `BodySizeLimit` middleware: 31 MB uploads, 2 MB JSON, declared and streamed | `test_edge_hardening.py` (4 tests) |
| F14 | CORS was the innermost middleware | 429 and 413 responses had no CORS headers; the browser showed an opaque network error instead of "slow down" | CORS added last (outermost); explicit methods and headers | `main.py` |
| F15 | `/health` returned 200 even when degraded, and was the only probe | load balancers could not route around a broken instance; a deep liveness probe would restart every replica on a DB blip | `/livez` (no dependencies) + `/readyz` (503 when Postgres, Redis, pgvector or storage is down) | `test_edge_hardening.py` probe tests |
| F16 | Monitor sweep ran on every worker with no lock, one query per project | N workers enqueued N duplicate monitor jobs | leader lock + one grouped query | `worker.py::monitor_sweep` |

### Security

| # | Gap | Risk | Fix | Pinned by |
|---|---|---|---|---|
| F17 | Rate-limit bucket keyed on a hash of ANY bearer string | a fresh random token per request = no rate limit | bucket = verified user id, else client IP | `test_random_bearer_tokens_do_not_buy_fresh_budgets` |
| F18 | Client IP taken from the LEFT-most `X-Forwarded-For` entry | clients chose their own bucket by sending the header | entry `trusted_proxy_hops` from the right | `test_spoofed_xff_cannot_choose_the_bucket` |
| F19 | `current_email` / `current_name` fell back to UNVERIFIED token decoding in production | `current_email` drives invitation matching: one route missing `current_user` away from accepting someone else's invite | unverified decode only when auth is disabled (dev) | `test_email_from_an_unverifiable_token_is_empty_when_auth_is_on` |
| F20 | SSRF guard checked only the first URL; httpx followed redirects itself | public URL -> 302 -> VPC address reached internal hosts | every hop re-checked, max 5 redirects | `test_untrusted_fetch.py` |
| F21 | PDF downloads buffered the whole body before the size check | a multi-GB response could exhaust worker memory | streamed with a byte cap | `test_untrusted_fetch.py` |
| F22 | Production booted on development settings (only auth-off was refused) | open `/metrics`, localhost CORS, schema auto-create, local blob storage, default DB credentials... all worked quietly wrong | `app/core/prod_checks.py`: 19 error rules + 8 warnings, all listed at once, API and worker | `test_prod_checks.py` (23 tests) |
| F23 | `/openapi.json` and `/redoc` stayed public in prod (only `/docs` was off) | full API surface published | all three off in prod | `main.py` |
| F24 | Readiness echoed raw dependency errors to the internet | hostnames and driver messages leaked | prod returns ok/down only | `main.py::_readiness` |
| F25 | Containers ran as root (API, worker, nginx) | any RCE is root in the container | backend uid 10001; `nginx-unprivileged` | CI asserts `User == 10001:10001` |
| F26 | Web tier had no Content-Security-Policy | XSS had no second line of defence | strict CSP (self + Google Fonts + Supabase + Sentry ingest) | `nginx.conf` |
| F27 | Job logs printed payloads verbatim, including invitees' email addresses | PII in logs | `_redact_payload` | `test_job_payload_logging_redacts_email` |
| F28 | Free AI Studio / `:free` OpenRouter tiers in the chain | prompts contain user-uploaded papers; free tiers may use them for training | Vertex AI provider (paid, ADC, no keys) leads the chain when `VERTEX_PROJECT` is set; prod warns on free tiers | `test_routing_lanes.py` |
| F47 | Gemini API key sent as `?key=` in the request URL | httpx puts the URL in every `HTTPStatusError`; tenacity's retry warning and the router's failover warning printed it on every 503, so live keys reached the log stream (and Cloud Logging in a deployment) | key sent as `x-goog-api-key` header; both log formatters redact credential shapes on the final line as a backstop | `test_secret_redaction.py` (header, 12 redaction cases, JSON stays valid) |

### Deploy, build and operations

| # | Gap | Fix |
|---|---|---|
| F29 | No infrastructure as code | `infra/gcp`: VPC, private Cloud SQL (PG16, PITR, 14 backups), Memorystore (AUTH), GCS, Artifact Registry with cleanup, Secret Manager, per-workload service accounts, WIF for CI, Cloud Run api/web/worker + migrate job, uptime + 5xx + disk alerts, budget alerts |
| F30 | Deploy was "SSH into a host and compose up" | CI `deploy`: WIF auth (no keys) -> re-tag the scanned image by digest -> run the migrate job -> roll out -> poll readiness -> rollback instructions on failure |
| F31 | CI scanned an `INSTALL_ML=0` image while release pushed the full ML image | CI builds and scans the production image and smoke-tests it (`/livez`, non-root) |
| F32 | Model weights downloaded from Hugging Face on every cold start | weights baked into the image; hub offline at runtime |
| F33 | CUDA torch wheels in a CPU image (~2.5 GB of unusable libraries) | CPU wheel index |
| F34 | `pip-audit ... \|\| true` inside a `continue-on-error` step could never surface | emits a warning annotation when it finds something |
| F35 | Migration CI used a plain Postgres and only ran `upgrade` once | pgvector image, re-run, `downgrade -1` + `upgrade`, integration tests |
| F36 | `terraform` had no gate | CI `infra` job: `fmt -check` + `validate` |
| F37 | RUNBOOK, SCALING, CICD, MIGRATIONS and the other ops docs were gitignored | a reviewer of the repository could not see how it is operated; they are tracked now |
| F38 | Stray `_nul` files (Windows redirect artefacts) committed at three paths | removed |
| F39 | `enforce_corpus_budget` read every tenant's evidence rows on each ingest | scoped to the project |
| F40 | Metric label used the raw path for unmatched routes | label is the route template or `unmatched` (bounded cardinality) |
| F41 | Web assets: no compression; `index.html` cacheable | gzip; hashed assets `immutable`; `index.html` `no-cache` (prevents a white screen after a release) |

---

## 2. Launch blockers (open)

| # | Item | Why it blocks | Owner / next step |
|---|---|---|---|
| L1 | **Billing is not enabled** on `veriscope-515119` | nothing billable can be created; Vertex AI cannot be called | You: Console -> Billing -> link an account. Then `infra/gcp/README.md` § Bootstrap |
| L2 | **No project or account deletion, no data export** | India's DPDP Act 2023 and GDPR give users erasure and access rights; a privacy policy cannot promise them without an endpoint. Touches ~15 tables, so it needs a reviewed cascade and a Postgres integration test, not a quick patch | Engineering, next. `DELETE /api/projects/{id}` (owner), `DELETE /api/me`, `GET /api/me/export` |
| L3 | **No per-user spend limit** | on paid Vertex one user can launch unlimited runs (10/min, unlimited projects); `run_max_llm_calls` caps a run, not a person | Decide the free and paid quotas (runs/day, tokens/month). Engineering: daily run quota + token ledger (PRODUCTION_TODO B4) |
| L4 | **Supabase Auth on its built-in SMTP** | the built-in sender is heavily rate-limited, so sign-up and password-reset emails stall after the first few users | Configure custom SMTP in Supabase (and SPF/DKIM/DMARC on the sending domain) |
| L5 | **Legal pages are starter drafts** (`LegalView.tsx` says so) | they must name the operating entity, sub-processors (Supabase, Google Cloud/Vertex AI, Groq/OpenRouter if kept, Semantic Scholar, arXiv), retention periods and the lawful basis | Counsel review. Confirm `support@veriscope.app` is a mailbox you own |
| L6 | **PDF parsing has no page or time cap** (PRODUCTION_TODO B2) | a crafted PDF can pin a CPU; uploads are parsed inside the HTTP request | Engineering: page cap + parse timeout in a subprocess, move upload parsing to a job |
| L7 | **First execution of new gates happens on push** | the pgvector integration tests and `terraform validate` have never run (no pgvector Postgres or Terraform on this machine) | Push; fix anything red before L1's apply |
| L8 | **Vertex model id and quota** | `vertex_model` defaults to `gemini-3.5-flash`; new projects get low per-minute quotas | After L1: confirm the id in Model Garden; request a quota increase sized to `section_draft_concurrency` x workers |
| L9 | **Local data cut-over** | the existing local corpus has its vectors in Qdrant | Run the backfill (section 5) |
| L10 | **The gate's false-accept rate on SciFact is 24%** (49/202 held-out pairs; 27% of CONTRADICT pairs verified) | "verified" cannot be marketed as "a source supports this" until it is measured lower. Quote-match still guarantees the span exists (0 fabricated citations holds); entailment is the weak layer. No threshold fixes it: the train frontier buys FA 10% only at FR 44% | Engineering: evaluate a stronger verifier with `python -m evals.scifact_gate --nli-model ...` (a larger NLI model, or an LLM verifier behind the NLI), ship only what moves the held-out numbers. Until then, product copy says "quote-verified, entailment-checked", never "proven" |
| L11 | **Rotate the Gemini API keys** | F47 wrote them to logs on every 503 (observed locally on 2026-11-25; any environment that ran the old client did the same) | You: revoke and reissue the AI Studio keys, update the secret, redeploy. Purge or restrict access to old log entries |

## 3. High priority, first weeks after launch (open)

| # | Item | Note |
|---|---|---|
| H1 | Python dependencies are lower-bound ranges with no lockfile | builds are not reproducible; a transitive release can break a deploy. Add a universal lock (`uv lock` / `pip-compile --generate-hashes`) and install from it in the Dockerfile |
| H2 | App metrics are not in Cloud Monitoring | GCP alerts cover uptime, 5xx and SQL disk; the gate/LLM/queue series (`/metrics`) need Managed Prometheus or an OTel collector to alert on GCP |
| H3 | No staging environment | copy `infra/gcp` with `name = "veriscope-stg"` and its own state prefix |
| H4 | Restore never rehearsed | run one PITR restore into a scratch instance; record RTO (target 1h) and RPO (minutes, PITR) in RUNBOOK |
| H5 | Load test covers `/health` only | `scripts/loadtest.py` needs a scenario that launches runs and polls status, run against staging |
| H6 | Uploads > 30 MB | signed-URL direct upload to GCS, then ingest from the object |
| H7 | `trusted_proxy_hops` behind web -> api | verify the real `X-Forwarded-For` shape once deployed (log it once), then set the value |
| H8 | Custom domain, HTTPS load balancer, Cloud Armor | edge rate limiting and WAF; run.app URLs are acceptable for a beta |
| H9 | Secret rotation procedure | DB password and Redis AUTH: rotate via Terraform + new secret version + redeploy; write it down |
| H10 | Share links never expire | add optional expiry; revoke exists |
| H11 | JWKS refresh is synchronous inside async code | `PyJWKClient` blocks the event loop once an hour on key refresh; move to a thread |
| H12 | No status page or incident-comms channel | users need somewhere to look when a run stalls |
| H13 | No product analytics | activation funnel (sign-up -> first run -> report opened -> Ask used) is invisible |
| H14 | Accessibility not audited | WCAG 2.2 AA pass on the report reader and evidence rail |
| H15 | Frontend main bundle > 500 kB | route-level code splitting |
| H16 | Log retention and content | define retention; research queries appear in logs; say so in the privacy policy |
| H17 | Supply chain extras | SBOM + image signing (cosign) + provenance on release |
| H18 | The LLM cache read is not best-effort | a Redis outage fails EVERY LLM call (`redis_store.cache_get` raises), not just caching. The queue needs Redis anyway, so this is availability, not correctness; make cache get/set swallow errors like the NLI memo does |
| H19 | Screening precision is barely bounded | 200 sampled negatives give specificity 99-100% but a precision floor of 23-37% at 1% prevalence; run `screening_bench --negatives 1000` before quoting precision |
| H20 | Gate false rejects: 31% of SUPPORT pairs on SciFact | 17 of 43 dev false rejects are the entity guard (`unsupported_entity`) rejecting abbreviations/synonyms; measure the guard on its own before tuning |

## 4. Before scale (open, by design)

| # | Item | Trigger |
|---|---|---|
| S1 | NLI and embeddings run in the API and worker processes behind one lock | when Ask latency or extraction time grows with concurrency: move to the `models` service (Cloud Run GPU) |
| S2 | Exact vector scan, no ANN index | a project passes ~100k chunks (SCALING.md) |
| S3 | `retrieve()` loads every chunk row of a project per call to build BM25 | same trigger; move lexical ranking to Postgres full-text search only after `evidence_bench` proves no recall loss |
| S4 | Redis Basic tier (no replica) | a Redis failure loses queued non-run jobs (runs are reconciled from Postgres). Standard tier with paying users |
| S5 | Cloud SQL zonal, shared-core | `db_high_availability = true`, `db_tier = db-custom-2-7680` with paying users |
| S6 | Single region | cross-region DR once there is an SLA to honour |

## 5. Cut over a local database to pgvector

```bash
# 1. New Postgres image (same major version; data volume is reused)
docker compose up -d postgres
docker compose exec postgres psql -U postgres -d research -c "REINDEX DATABASE research;"
# 2. Rebuild the backend images (models are now baked in; first build downloads ~1 GB once)
docker compose --profile app build
# 3. Start Qdrant only to copy vectors out of it, then the app
docker compose --profile qdrant up -d qdrant
docker compose --profile app up -d
# 4. Copy vectors (no re-embedding for anything Qdrant has); exits 0 when complete
docker compose --profile app exec worker python scripts/backfill_pgvector.py
# 5. Measure before trusting it: recall must not drop
docker compose --profile app exec worker python -m evals.evidence_bench --report <report_id> --rerank
# 6. Retire Qdrant
docker compose stop qdrant
```

The REINDEX is needed because the old image was Alpine (musl) and the new one
is Debian (glibc); they sort text differently, and text indexes built under one
are not reliable under the other.

## 6. Verified sound (do not re-open)

- Every API route requires a verified user except `GET /api/shared/{slug}`,
  which is public by design (checked by walking the route table: 63 of 64).
- Object-level authorization (`_get_project`) on every project-scoped route.
- JWT audience and issuer checked; HS256 refused in production; JWKS cached.
- The verification gate fails closed in production when NLI is unavailable.
- Per-run execution lock with heartbeat; idempotency key on pipeline submit.
- Pagination on every list endpoint; the notebook N+1 is gone.
- Security headers on API responses; `default-src 'none'` CSP on JSON.
- Secret scanning (gitleaks) blocks; npm audit blocks at high; Trivy reports.
- `.env` files are gitignored and untracked.
