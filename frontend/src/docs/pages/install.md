Veriscope runs two ways: **Docker for one command**, or **from source** if you plan to
change the code. Both need at least one free LLM API key.

## Prerequisites

| | Version | Notes |
| --- | --- | --- |
| Docker | any recent | Required for Postgres, Redis and Qdrant either way. |
| Python | 3.12 | Source install only. |
| Node | 18+ | Source install only. |
| LLM key | at least one | [Gemini](https://aistudio.google.com/apikey) or [Groq](https://console.groq.com) — both have free tiers. |

## Option A — Docker

One command runs the whole thing: UI, API, worker and infrastructure. The `app` profile
includes a containerised frontend (nginx serving the built bundle and proxying `/api`),
so the entire product lives at a single URL.

```bash
cp .env.example backend/.env
```

```bash
docker compose --profile app up --build
```

Open **http://localhost:8080**.

- **Zero-config auth** — the demo runs open by default (`AUTH_DISABLED=true`), so no
  Supabase project is needed. Visitors hit the landing page, click *Get started*, and go
  straight into the workspace.
- **Change the port** — `WEB_PORT=3000 docker compose --profile app up`.
- **Scale workers** — `docker compose --profile app up --scale worker=3`. Job claim is
  atomic, so replicas are safe.

```diagram:deployment
```

## Option B — from source

```bash
docker compose up -d
```

That brings up Postgres on `:5433`, Redis on `:6380` and Qdrant on `:6333` — the stateful
parts only.

```bash
cp .env.example backend/.env
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -e . && pip install -e ".[ml]"
```

On macOS and Linux use `source .venv/bin/activate` instead. The `[ml]` extra installs the
local embedding, reranking and NLI models — roughly 2 GB.

Then run three processes, in three terminals:

```bash
uvicorn app.main:app --port 8210
```

```bash
python -m app.worker
```

```bash
cd ../frontend && npm install && npm run dev
```

Open **http://localhost:5173**.

:::warn Run exactly one worker locally
The atomic job-claim path is exercised by the compose setup. When running from source,
start a single worker so two processes cannot race for the same run.
:::

## What the `[ml]` extra buys you

| Without `[ml]` | With `[ml]` |
| --- | --- |
| Retrieval degrades to BM25 only. | Hybrid BM25 + dense retrieval with cross-encoder reranking. |
| NLI entailment is skipped. | The third gate layer runs — out-of-context quotes are caught. |
| Quote-match remains the hard gate. | Quote-match **and** entailment are both hard gates. |

:::danger Never ship production without NLI
`ML_NLI_ENABLED=false` is refused at boot when `APP_ENV=prod`. Without it the gate would
ship claims on quote-match alone, silently dropping the out-of-context check. The startup
assertion is the friendly early warning; the gate itself is the hard backstop.
:::

## Configuring keys

Everything lives in `backend/.env`. Only the LLM keys are required — every other setting
has a working default. See [Configuration](#/docs/reference/configuration) for the full
surface, and [Configure LLM providers](#/docs/how-to/configure-providers) for how the
four-provider fleet is routed.

```bash
GEMINI_API_KEY=...
GROQ_API_KEY=...
AUTH_DISABLED=true
```

## Verify the install

```bash
cd backend && python -m pytest -q
```

```bash
cd backend && python evals/run_evals.py
```

The eval gate must pass before any change ships. See [Evaluation](#/docs/reference/evals).
