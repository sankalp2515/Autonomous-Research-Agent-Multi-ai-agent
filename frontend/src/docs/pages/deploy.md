This guide covers taking Veriscope from a local demo to a deployment with real users.

```diagram:deployment
```

## 1. Turn on authentication

The demo runs open. A real deployment must not.

```bash
APP_ENV=prod
AUTH_DISABLED=false
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<frontend sign-in key, not a secret>
```

The frontend signs in with the publishable key via `supabase-js`; the backend verifies
access tokens against the project **JWKS** endpoint (RS256/ES256), with the legacy HS256
secret as a fallback only.

:::danger The publishable key is never used for verification
It is a client credential. Verification uses JWKS. If you find code verifying a token
against the publishable key, that is a security bug, not a shortcut.
:::

`AUTH_DISABLED=true` is refused at boot when `APP_ENV=prod`.

Build the frontend with the matching values, or sign-in has no way to work:

```bash
VITE_SUPABASE_URL=... VITE_SUPABASE_ANON_KEY=... npm run build
```

If the backend requires auth and the frontend build has no Supabase keys, the app says so
explicitly rather than 401-ing on every call.

## 2. Lock down the edges

```bash
CORS_ALLOW_ORIGINS=["https://your-deployment"]
RATE_LIMIT_PER_MIN=900
PIPELINE_RATE_LIMIT_PER_MIN=10
METRICS_TOKEN=<random>
TRUST_FORWARDED_FOR=true
```

Set `TRUST_FORWARDED_FOR` **only** when you actually run behind a proxy you control —
otherwise clients can spoof their own IP and defeat rate limiting.

## 3. Size the run capacity

```bash
MAX_CONCURRENT_RUNS_PER_PROJECT=2
MAX_QUEUE_DEPTH=200
RUN_MAX_WALL_SECONDS=5400
RUN_MAX_LLM_CALLS=200
```

Above `MAX_QUEUE_DEPTH` the API sheds load with a 503 rather than accepting work it cannot
finish. Scale workers horizontally — job claim is atomic:

```bash
docker compose --profile app up --scale worker=3
```

## 4. Keep the verification stack on

```bash
ML_NLI_ENABLED=true
ML_EMBEDDINGS_ENABLED=true
ML_RERANK_ENABLED=true
```

If the API container should stay light, run the `models` profile and point at it:

```bash
INFERENCE_SERVICE_URL=http://models:8100
```

## 5. Storage

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/veriscope
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_AUTO_CREATE=false
QDRANT_URL=http://qdrant:6333
REDIS_URL=redis://redis:6379/0
BLOB_BACKEND=s3
```

Turn `DB_AUTO_CREATE` off in production and run migrations explicitly. Postgres is the
only store that needs a backup policy — Qdrant rebuilds from it and Redis is disposable.

## 6. Observability

```bash
LOG_FORMAT=json
SENTRY_DSN=...
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

A separate compose file ships the observability stack:

```bash
docker compose -f docker-compose.observability.yml up -d
```

## Pre-flight checklist

- [ ] `APP_ENV=prod` and `AUTH_DISABLED=false`
- [ ] `CORS_ALLOW_ORIGINS` names only your origins
- [ ] `METRICS_TOKEN` set — the metrics endpoint is not public
- [ ] `ML_NLI_ENABLED=true` (boot will refuse otherwise)
- [ ] `DB_AUTO_CREATE=false`, migrations applied
- [ ] Frontend built with the Supabase build args
- [ ] `python -m pytest -q` green
- [ ] `python evals/run_evals.py` gate passing
- [ ] `npx tsc -b && npx vite build` clean

## Related

- [Configuration](#/docs/reference/configuration)
- [Troubleshooting](#/docs/how-to/troubleshoot)
