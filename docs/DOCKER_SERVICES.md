# Docker services — what every container actually does

**Private engineering reference.** This file is deliberately *not* part of the
public `/docs` screen. It is here so that when you come back to this repo in six
months you can answer "what is this container for, and what breaks if I stop it?"
without reading three compose files.

There are **three compose files**, and they are separate on purpose.

| File | Loaded | Purpose |
|---|---|---|
| `docker-compose.yml` | always | Infrastructure, plus the app behind opt-in profiles. |
| `docker-compose.override.yml` | **automatically**, by convention | Dev-only bind mounts and readable logs. |
| `docker-compose.observability.yml` | only with an explicit `-f` | Metrics, logs, traces. Separate because it OOM-killed a dev host. |

---

## 1. The three always-on infrastructure services

These run with a bare `docker compose up -d` — no profile needed. They are the
stateful floor everything else sits on.

### `postgres` — the system of record

- **Image:** `pgvector/pgvector:pg16` (Postgres 16 + pgvector; chunk vectors live here). Moving an existing alpine volume: run `REINDEX DATABASE research;` once (musl vs glibc collation).
- **Host port:** `${POSTGRES_PORT:-5433}` → container `5432`
- **Volume:** `pg_data:/var/lib/postgresql/data`
- **Credentials:** `postgres` / `postgres`, database `research`
- **Healthcheck:** `pg_isready -U postgres -d research`, every 5s

**What it holds:** everything durable. Projects, documents, chunks (text and
metadata), claims, claim evidence, citations, runs and their checkpoints,
reports, answers, notes, saved notebook items, memories, watches, monitor
alerts, comparisons, graph nodes and edges, audit log, feedback.

**What breaks without it:** everything. This is the only container whose data
loss is unrecoverable, and therefore the only one that needs a backup policy.

**Note the non-standard host port.** It is `5433`, not `5432`, because a dev
machine usually already has a Postgres. `DATABASE_URL` in `backend/.env` must
match when running the backend from source. Inside the compose network the API
and worker talk to `postgres:5432` directly — that is set via the `environment`
block, which overrides `env_file`.

### `redis` — disposable state

- **Image:** `redis:7-alpine`, started with `--appendonly yes`
- **Host port:** `${REDIS_PORT:-6380}` → container `6379`
- **Volume:** `redis_data:/data`
- **Healthcheck:** `redis-cli ping`

**What it holds:** run progress events (what the SSE stream replays), the LLM
response cache (`LLM_CACHE_TTL_SECONDS`, 24h), provider rate-limit throttle
buckets, run locks for atomic job claim, and the cached project map (30 min TTL).

**What breaks without it:** the live run feed goes quiet, the LLM cache misses
(slower and more expensive, not wrong), and the map recomputes on every open.
Nothing a user *sees in a report* comes from Redis — that is the custody rule,
and it is the reason losing this container is survivable.

Note that `appendonly yes` gives it persistence even though the architecture
treats it as disposable. That is a convenience for restarts, not a guarantee
anything relies on.

### `qdrant` — previous vector store (cut-over only)

- **Profile:** `qdrant` — not started by default. Vectors now live on
  `chunks.embedding` in Postgres (pgvector).
- **Use:** `docker compose --profile qdrant up -d qdrant`, then
  `docker compose --profile app exec worker python scripts/backfill_pgvector.py`
  to copy existing vectors without re-embedding. Remove after one release.

### `frontend` — nginx serving the built bundle

- **Build:** `./frontend`, with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`
  passed as **build args** (they are baked into the bundle at build time — you
  cannot change them by restarting the container)
- **Host port:** `${WEB_PORT:-8080}` → container `80`
- **Depends on:** `api`

This is what makes the demo one URL. nginx serves the static bundle and proxies
`/api` to the `api` container, so there is no CORS configuration and no second
port for a reviewer to discover.

**Consequence worth remembering:** turning sign-in on is a **rebuild**, not a
restart. `AUTH_DISABLED=false` on the backend without the two `VITE_SUPABASE_*`
build args produces an app that 401s on every call — the frontend detects that
specific mismatch and shows a config notice rather than failing silently.

### `api` — FastAPI

- **Build:** `./backend`
- **Host port:** `8210` → container `8000`
- **Volume:** `hf_cache:/models`
- **Depends on:** postgres, redis — both `condition: service_healthy`
- **Key environment:**
  - `DATABASE_URL`, `REDIS_URL` → the in-network hostnames
  - `AUTH_DISABLED` defaults to `true` for the zero-config demo
  - `INFERENCE_SERVICE_URL` empty → models run in-process
  - `HF_HOME=/models` and `HF_HUB_DOWNLOAD_TIMEOUT=30`

Serves the REST API and the SSE progress stream. It does **not** run pipelines —
`POST /api/pipeline` returns `202` and enqueues.

**The `HF_*` variables are not incidental.** Without a persistent `HF_HOME` a
fresh container re-downloads roughly 500 MB of embedding/rerank/NLI weights and
gets rate-limited by Hugging Face; that hung a worker for over ten minutes. The
timeout makes it fail fast instead of hanging forever, and the shared `hf_cache`
volume means api, worker and models all download once between them.

**`environment` beats `env_file`.** Anything set in the compose `environment`
block cannot be overridden from `backend/.env`. That is intentional for the
in-network URLs, and it is the reason `AUTH_DISABLED` is exposed as
`${AUTH_DISABLED:-true}` — a root `.env` is the knob, not `backend/.env`.

### `worker` — the pipeline executor

- **Build:** `./backend`, command `python -m app.worker`
- **No ports.** It is a consumer, not a server.
- **Volume:** `hf_cache:/models` (same cache as the api)
- **Same dependency and env story as `api`**

This is where a research run actually happens: search, ingest, per-paper
extraction, drafting, the verification gate. It is the container that will use
your CPU and RAM, because the local ML stack loads here.

**Scale it with `--scale worker=3`.** Job claim is atomic (`tests/test_run_lock.py`),
so replicas cannot both pick up the same run. When running from source, run
exactly one — that path is not exercised by the compose setup.

---

## 3. The `models` profile — the optional inference tier

Started with `docker compose --profile models up`. Off by default.

- **Build:** `./backend`, command `uvicorn app.model_server:app --port 8100`
- **Host port:** `${MODELS_PORT:-8100}`
- **Volume:** `hf_cache:/models`
- **Healthcheck:** HTTP `GET /health` every 15s
- **`INFERENCE_SERVICE_URL: ""` — forced empty**

Serves embeddings, reranking and NLI over HTTP so inference scales independently
of the API and comes off the API's request-path lock.

**To use it:** set `INFERENCE_SERVICE_URL=http://models:8100` in a **root**
`.env` and bring up both profiles:

```bash
docker compose --profile app --profile models up --scale models=3
```

**Why `INFERENCE_SERVICE_URL` is pinned empty inside this container:** it *is*
the inference tier. If it inherited a value it would proxy to itself, and the
server refuses to boot rather than recurse.

**Port `8100` is authoritative**, per this compose file and the `uvicorn` command.
Some older notes elsewhere in the repo used `8300`; those are wrong.

---

## 4. `docker-compose.override.yml` — dev only, auto-loaded

Compose loads this **by convention, without being asked**. That is convenient
locally and dangerous in production, which is why any real deployment must use
an explicit `docker compose -f docker-compose.yml ...`.

It does two things to `api` and `worker`:

1. **Bind-mounts `./backend/app` to `/app/app` read-only.** Without this, a
   containerised worker runs a baked image and silently executes *stale code
   after every edit*. That invalidated three separate verification runs before
   anyone noticed. With it, `docker compose --profile app restart worker api`
   picks up changes in seconds — no rebuild, no 2 GB Torch re-download.
2. **Sets `LOG_FORMAT: console`** so logs are readable rather than JSON.

**Historical landmine, now removed.** This file used to pin
`RESEARCH_MAX_PAPERS: "10"` as a "temporary" diagnostic override. It was never
removed, so every run for months was capped at a 10-paper corpus — which is most
of why reports read thin. If you ever add a temporary override here, add a
removal task in the same commit.

---

## 5. `docker-compose.observability.yml` — separate on purpose

```bash
docker compose -f docker-compose.observability.yml up -d
```

**Do not merge this into the main compose file.** Running these five containers
alongside the ML worker (roughly 2 GB of Torch models) OOM-killed a dev host —
every container exited 137. Keeping it a distinct compose project makes
co-launching an explicit choice rather than an accident. Budget ~2 GB RAM for
this stack *alone*, on top of the app; 16 GB total is comfortable.

| Service | Image | Port | Role |
|---|---|---|---|
| `prometheus` | `prom/prometheus:v2.54.1` | 9090 | Scrapes API metrics; loads `alerts.yml`. |
| `tempo` | `grafana/tempo:2.6.1` | 3200, 4317 (gRPC), 4318 (OTLP HTTP) | Trace store. 4318 is what the app exports to. |
| `loki` | `grafana/loki:3.2.0` | 3100 | Log store. |
| `promtail` | `grafana/promtail:3.2.0` | — | Ships container logs to Loki. Mounts the Docker socket and `/var/lib/docker/containers` read-only. |
| `grafana` | `grafana/grafana:11.2.0` | 3001 → 3000 | Dashboards, provisioned from `deploy/observability/`. |

**The networking is the subtle part.** This is a *separate compose project*, so
it does not share a network with the app. It reaches the app over the **host**:

- Prometheus scrapes `host.docker.internal:8210`. On Linux this only resolves
  because of the `extra_hosts: host.docker.internal:host-gateway` entry.
- The app pushes OTLP traces to `localhost:4318`, which requires
  `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` in
  `backend/.env`.

Meanwhile the main compose file sets `OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4318`
on api and worker — the in-network name. That is a harmless no-op when the
observability stack is down, but it means **the endpoint differs depending on
whether the app is containerised or running from source**. From source, use
`localhost:4318`.

:warning: **Grafana runs with anonymous Admin access** (`GF_AUTH_ANONYMOUS_ENABLED=true`,
`GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`). That is a local-convenience setting. Set a
password or disable anonymous access before exposing it anywhere at all.

---

## 6. Volumes — what is precious and what is not

| Volume | Used by | Losing it means |
|---|---|---|
| `pg_data` | postgres | **Unrecoverable data loss.** Back this up. |
| `qdrant_data` | qdrant (cut-over only) | Nothing: pgvector is the store now. |
| `redis_data` | redis | Nothing that matters. Cache and progress. |
| `hf_cache` | api, worker, models | Re-download ~500 MB of model weights, with rate-limit risk. |
| `prom_data`, `tempo_data`, `loki_data`, `grafana_data` | observability | Historical telemetry only. |

A `docker compose down -v` on the main file destroys `pg_data`. There is no
confirmation prompt. This is the one command in the repo that can lose real work.

---

## 7. Common operations

```bash
# infra only — the normal mode when developing the backend from a venv
docker compose up -d

# the whole app at http://localhost:8080
docker compose --profile app up --build

# pick up backend code changes (override.yml bind-mounts the source)
docker compose --profile app restart worker api

# more throughput on runs
docker compose --profile app up --scale worker=3

# separate inference tier
docker compose --profile app --profile models up

# telemetry, deliberately separate
docker compose -f docker-compose.observability.yml up -d

# a production-shaped launch: ignore the dev override explicitly
docker compose -f docker-compose.yml --profile app up -d
```

## 8. Port map

| Port | Service | Override |
|---|---|---|
| 8080 | frontend (nginx) | `WEB_PORT` |
| 8210 | api | fixed in compose |
| 8100 | models | `MODELS_PORT` |
| 5433 | postgres | `POSTGRES_PORT` |
| 6380 | redis | `REDIS_PORT` |
| 6333 / 6334 | qdrant HTTP / gRPC | `QDRANT_PORT` / `QDRANT_GRPC_PORT` |
| 9090 | prometheus | fixed |
| 3200 / 4317 / 4318 | tempo query / OTLP gRPC / OTLP HTTP | fixed |
| 3100 | loki | fixed |
| 3001 | grafana | fixed |

## 9. Things that have actually gone wrong here

Kept as a list because each one cost real debugging time.

1. **Stale code in the worker container** — fixed by the bind mount in
   `docker-compose.override.yml`. If you ever run without the override, remember
   the image is authoritative and you must rebuild.
2. **A "temporary" `RESEARCH_MAX_PAPERS: 10`** left in the override file for
   months, capping every corpus at 10 papers.
3. **Observability co-launched with the ML worker** → OOM, all containers
   exit 137. Hence the separate file.
4. **Hugging Face rate-limiting a fresh container** → worker hung >10 minutes.
   Hence `HF_HOME` on a shared volume and a 30s download timeout.
5. **Windows `winnat` reserving port 6333** → hence every host port is
   env-overridable.
