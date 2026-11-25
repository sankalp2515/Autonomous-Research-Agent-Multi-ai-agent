# Deployment, rollback and incident runbook

Operational procedures for Veriscope: environments, migrations, deploy,
rollback, recovery, and what to do when an alert fires. The production target
is Google Cloud (`infra/gcp`); the compose stack (`deploy/docker-compose.prod.yml`)
is the self-hosted alternative and follows the same rules.

## Environments

`APP_ENV` ∈ `dev | staging | prod` drives behavioural guards, not just labels.

**prod refuses to boot on development settings** (`app/core/prod_checks.py`,
pinned by `tests/test_prod_checks.py`). Every problem is listed in one error:
auth disabled, missing/insecure `SUPABASE_URL`, localhost or `*` CORS origins,
`DB_AUTO_CREATE=true`, a localhost or default-credential database, localhost
Redis, the local blob backend, no LLM provider, NLI off, no `METRICS_TOKEN`,
a localhost `APP_BASE_URL`. Warnings (logged, not blocking): console logs, no
Sentry, untrusted `X-Forwarded-For`, a free-tier model that may train on
prompts, dual-write still on.

Secrets: Secret Manager in GCP (mounted as env vars by Cloud Run), `.env` on a
laptop (gitignored). No credential is ever in an image, the repo, or CI - CI
authenticates to GCP through Workload Identity Federation.

Separate databases per environment. Never point staging at prod data.

## Database migrations

Alembic is the source of truth (`backend/alembic/`). Every revision is written
**idempotent** (checks before it adds), and CI proves the chain applies to a
clean Postgres 16 + pgvector, re-runs, and survives `downgrade -1` / `upgrade`.

**Order of a deploy:** migrate first, then roll out code. On GCP that is the
`veriscope-migrate` Cloud Run Job, which CI executes and waits on before
deploying any service. On compose, the `api` container runs it
(`RUN_MIGRATIONS=1`).

**Expand-only rule:** the PREVIOUS release must keep working on the NEW schema.
Add columns nullable or defaulted; never drop or rename in the release that
stops using something - drop it one release later. This is what lets an app
rollback skip the database entirely.

New change: `alembic revision --autogenerate -m "..."` -> review -> make it
idempotent like 0005-0008 -> commit.

## Deploy (GCP)

Push to `main` (or a `v*` tag). CI runs every gate, pushes images to GHCR,
then the `deploy` job (environment `production`, add required reviewers in repo
settings to make it a manual approval):

1. re-tags the scanned images into Artifact Registry - same digest, no rebuild;
2. runs `veriscope-migrate` and waits;
3. deploys `veriscope-worker`, `veriscope-api`, `veriscope-web`;
4. polls `api/readyz`, `web/livez`, `web/api/health`; fails red if any never
   becomes ready, with the rollback commands in the job summary.

## Rollback

Because migrations are expand-only, **app rollback and schema are decoupled**.

1. **App (normal case)** - send traffic back to the previous revision:
   ```bash
   gcloud run revisions list --service veriscope-api --region asia-south1
   gcloud run services update-traffic veriscope-api --region asia-south1 --to-revisions=<previous>=100
   ```
   Repeat for `veriscope-web`, and redeploy the worker at the previous image
   tag (`gcloud run deploy veriscope-worker --image .../backend:<previous sha>`).
   In-flight runs resume from their last node checkpoint; the per-run lock
   guarantees one executor.
2. **Bad migration** - roll forward with a corrective revision. `alembic
   downgrade` only for a narrow, reviewed, reversible change; the baseline
   refuses to downgrade.
3. **Config** - revert the env var or secret version and deploy a new revision;
   no image change needed.
4. **Vector store cut-over** (one release only): `VECTOR_BACKEND=qdrant` returns
   reads to Qdrant if it is still running and was dual-written.

## Restart and recovery behaviour

- **Jobs are leased.** A claimed job holds `jobs:lease:<id>`, renewed every 30s
  by the executing worker. If the worker dies, the lease lapses within 120s and
  the next maintenance sweep (every 60s, leader-gated, any surviving worker)
  requeues it. Recovery does not wait for a restart, and **nothing is ever
  deleted from the queue** (the previous boot recovery wiped it, dropping
  queued emails and imports).
- **Runs are reconciled.** A run at `queued`/`running` older than two minutes
  with no job and no live executor gets a job. Its launch filters come from
  `runs.launch_params`, so a recovered run answers the question the user asked.
- **Poison jobs stop.** After 3 attempts (failures or worker deaths) a job goes
  to `jobs:dead`; if it was a run, the run is marked `failed` with a reason and
  the user can resume it. Inspect: `LRANGE jobs:dead 0 -1`.
- **SIGTERM is graceful.** The worker stops claiming, gives the current job
  `WORKER_SHUTDOWN_GRACE_SECONDS` (8s; Cloud Run kills at 10s), then returns it
  to the queue without counting an attempt.
- **What is disposable:** Redis (queue, cache, locks, progress) is rebuildable
  from Postgres. Losing it loses in-flight progress and cache, never verified
  data. Postgres is the system of record, vectors included.

## Health

| endpoint | meaning | used by |
|---|---|---|
| `/livez` (api, worker, web) | process can answer; checks NO dependency | liveness probes |
| `/readyz` (api) | Postgres, Redis, pgvector schema, blob store all OK; **503** otherwise | uptime check, deploy verification |
| `/readyz` (worker) | loop ticked in the last 60s and Redis reachable | worker liveness probe |
| `/health`, `/api/health` | aliases of api `/readyz` (the second is reachable through the web origin) | smoke tests |
| `/metrics` | Prometheus; api requires `METRICS_TOKEN` | scraping |

A liveness probe never checks dependencies: one that fails on a database blip
restarts every replica at once and turns a brief outage into a full one.

## When an alert fires

| alert | first look | likely cause / action |
|---|---|---|
| Veriscope is down (uptime) | `gcloud run services describe veriscope-api`; Cloud Run logs | bad revision -> roll back; `/readyz` 503 -> which dependency (logs name it) |
| API 5xx rate | Error Reporting / Sentry, filter by `x-request-id` | roll back if it started with a deploy |
| Cloud SQL disk > 80% | Cloud SQL -> Storage | autoresize is on; check for a runaway table (`runs.checkpoint` growth) |
| `retrieval_dense_degraded_total` rising | worker logs "dense ranking failed" | pgvector query failing -> reports are lexical-only; treat as a quality incident |
| `job_queue_depth{queue="dead"}` > 0 | `LRANGE jobs:dead 0 -1` | a job failed 3x; the run row carries the error |
| Budget 50/90/100% | Billing -> Reports, group by SKU | Vertex tokens (cap `run_max_llm_calls`), worker instances, Cloud SQL tier |

## A credential reached the logs

Happened once (2026-11-25): Gemini keys were sent in the URL and printed by
every retry warning (PRODUCTION_READINESS F47, fixed). If it happens again:

1. Revoke the key at the provider and issue a new one (AI Studio: API keys page;
   Groq / OpenRouter: their key consoles). Revoke first; a key in a log is public.
2. Add the new value as a new Secret Manager version, redeploy api + worker.
3. Restrict and, where retention allows, purge the log entries
   (`logName` + time window) in Cloud Logging.
4. Find the source: grep a recent log export for `[REDACTED]` — the formatter
   backstop marks what it caught, which names the code path that leaked.

## Quality incident: the benchmarks moved

`evals.yml` (weekly) runs the research-synthesis benchmarks informationally. A
drop in screening recall or a rise in the SciFact false-accept rate is a
quality incident even with every request green: run `python -m
evals.screening_bench` / `python -m evals.scifact_gate` on the previous and the
current commit and diff the per-record causes before touching thresholds.

## Post-deploy checklist

1. CI `deploy` job green (it already polled readiness).
2. Worker logs show `worker heartbeat` and no `maintenance failed`.
3. Launch one small run; it reaches `completed` / `completed_with_gaps`.
4. `evals.yml` groundedness gates green for this commit.
5. `python -m evals.report_integrity --report <id>` on the run from step 3 reports 0 errors.
