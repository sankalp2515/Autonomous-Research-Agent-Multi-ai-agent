Every setting is read from `backend/.env` (or the environment) by `app/core/config.py`.
Names below are the environment-variable form; defaults are the shipped values.

:::note Only the LLM keys are required
Everything on this page has a working default. Start with one provider key and change
nothing else until you have a reason.
:::

## Application

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `dev` | `dev` / `staging` / `prod`. `prod` enables fail-fast boot checks. |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` | `console` for readable local logs. |
| `APP_BASE_URL` | `http://localhost:8080` | Used in outbound email links. |

## Authentication

| Variable | Default | Notes |
| --- | --- | --- |
| `AUTH_DISABLED` | `true` | Refused at boot when `APP_ENV=prod`. |
| `SUPABASE_URL` | — | |
| `SUPABASE_PUBLISHABLE_KEY` | — | Frontend sign-in key. Not a secret, **never** used for verification. |
| `SUPABASE_JWT_SECRET` | — | Legacy HS256 fallback only; JWKS is preferred. |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | |
| `SUPABASE_JWT_ISSUER` | `{supabase_url}/auth/v1` | |

## Edges and limits

| Variable | Default | Notes |
| --- | --- | --- |
| `CORS_ALLOW_ORIGINS` | localhost dev origins | Narrow this in production. |
| `RATE_LIMIT_PER_MIN` | `900` | General API. |
| `PIPELINE_RATE_LIMIT_PER_MIN` | `10` | Run launches. |
| `MAX_CONCURRENT_RUNS_PER_PROJECT` | `2` | Admission cap. |
| `MAX_QUEUE_DEPTH` | `200` | Above this the API returns 503. |
| `METRICS_TOKEN` | — | Guards the metrics endpoint. |
| `TRUST_FORWARDED_FOR` | `false` | Only enable behind a proxy you control. |

## Storage

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/research` |
| `DB_POOL_SIZE` | `10` |
| `DB_MAX_OVERFLOW` | `20` |
| `DB_AUTO_CREATE` | `true` — turn off in production |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `QDRANT_URL` | `http://localhost:6333` |
| `QDRANT_COLLECTION` | `chunks` |
| `BLOB_BACKEND` | `local` — or `s3` |
| `LIBRARY_ENABLED` | `true` |
| `LIBRARY_DIR` | `data/library` |

## LLM providers

| Variable | Default | RPM |
| --- | --- | --- |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `gemini-2.0-flash` | `GEMINI_RPM` 10 |
| `GROQ_API_KEY` / `GROQ_MODEL` | `llama-3.3-70b-versatile` | `GROQ_RPM` 25 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | `deepseek-chat` | `DEEPSEEK_RPM` 20 |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | `llama-3.3-70b-instruct:free` | `OPENROUTER_RPM` 15 |
| `NVIDIA_API_KEY` / `NVIDIA_MODEL` | `meta/llama-3.3-70b-instruct` | `NVIDIA_RPM` 40 |
| `LLM_CACHE_TTL_SECONDS` | `86400` | |

## Local ML

| Variable | Default |
| --- | --- |
| `ML_EMBEDDINGS_ENABLED` | `true` |
| `ML_RERANK_ENABLED` | `true` |
| `ML_NLI_ENABLED` | `true` — refused off when `APP_ENV=prod` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_DIM` | `384` |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| `NLI_MODEL` | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` |
| `INFERENCE_SERVICE_URL` | — offload to the `models` profile |
| `INFERENCE_SERVICE_TIMEOUT` | `120.0` |

## The gate

| Variable | Default | Meaning |
| --- | --- | --- |
| `NLI_ENTAILMENT_THRESHOLD` | `0.60` | Below this, the claim fails. |
| `NLI_CONTRADICTION_THRESHOLD` | `0.40` | A contradiction always fails. |
| `NLI_NEUTRAL_REJECT_THRESHOLD` | `0.85` | Strongly-neutral verdicts are rejected. |
| `QUOTE_FUZZY_THRESHOLD` | `0.92` | Tolerance for PDF-extraction artefacts only. |
| `GATE_ENTITY_CHECK_ENABLED` | `true` | Entity consistency between claim and chunk. |

## Sourcing and screening

| Variable | Default |
| --- | --- |
| `SCREEN_MAX_CANDIDATES` | `50` |
| `RESEARCH_MAX_PAPERS` | `28` |
| `CITATION_WEIGHT` | `0.15` |
| `RECENCY_WEIGHT` | `0.20` |
| `RECENCY_HORIZON_YEARS` | `15` |
| `PRACTITIONER_SOURCES_ENABLED` | `false` |
| `BLOG_DOMAIN_WHITELIST` | curated list |
| `SEMANTIC_SCHOLAR_API_KEY` / `GITHUB_TOKEN` / `TAVILY_API_KEY` | — |

## Ingestion

| Variable | Default |
| --- | --- |
| `INGEST_MAX_PDF_MB` | `50` |
| `INGEST_PDF_CONCURRENCY` | `4` |
| `INGEST_DOWNLOAD_CONCURRENCY` | `10` |
| `CORPUS_MAX_EMBEDDED_CHUNKS` | `4000` |

## Retrieval

| Variable | Default |
| --- | --- |
| `RETRIEVAL_TOP_K` | `12` |
| `SECTION_TOP_K` | `20` |
| `SECTION_MAX_PER_DOC` | `3` |
| `RRF_K` | `60` |

## Evidence extraction

| Variable | Default |
| --- | --- |
| `EVIDENCE_MAX_PAPERS` | `22` |
| `EVIDENCE_EXTRACT_CONCURRENCY` | `4` |
| `EVIDENCE_MAX_DIMENSIONS` | `6` |
| `EVIDENCE_DIMENSION_RETRIEVAL` | `true` |
| `EVIDENCE_DIMENSION_RERANK` | `true` |
| `EVIDENCE_CHUNKS_PER_DIMENSION` | `6` |
| `EVIDENCE_MAX_CHUNKS_PER_PAPER` | `24` |
| `EVIDENCE_CHUNKS_PER_PAPER` | `8` — legacy single-query fallback |
| `EVIDENCE_RECOVERY_ENABLED` | `true` |
| `EVIDENCE_RECOVERY_MAX_PAPERS` | `24` |
| `EVIDENCE_RECOVERY_CONCURRENCY` | `4` |
| `EVIDENCE_ABSENCE_MIN_QUERIES` | `2` |
| `EVIDENCE_ABSENCE_MIN_CHUNKS` | `4` |

The last two are the teeth of the `not_reported` rule — see
[Cell states](#/docs/explanation/cell-states).

## Budgets

| Variable | Default |
| --- | --- |
| `RUN_MAX_WALL_SECONDS` | `5400` |
| `RUN_MAX_LLM_CALLS` | `200` |
| `SECTION_MAX_REGENS` | `2` |
| `SUBQUESTION_MAX_REPLANS` | `1` |

## Observability

| Variable | Default |
| --- | --- |
| `SENTRY_DSN` | — |
| `OTEL_ENABLED` | `false` |
| `OTEL_SERVICE_NAME` | `veriscope-api` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | — |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | — / `veriscope` |

## Email

| Variable | Default |
| --- | --- |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | — |
| `SMTP_FROM` | `Veriscope <no-reply@veriscope.app>` |
| `SMTP_STARTTLS` | `true` |

## Frontend build

| Variable | Purpose |
| --- | --- |
| `VITE_SUPABASE_URL` | Sign-in endpoint. |
| `VITE_SUPABASE_ANON_KEY` | Publishable sign-in key. |
| `VITE_API_TARGET` | Dev-server proxy target. |
