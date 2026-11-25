# CI/CD Pipeline

One GitHub Actions workflow (`.github/workflows/ci.yml`) gates every push/PR and
releases + deploys on `main` and `v*` tags. Each job is a **quality gate** — a
red job blocks the merge.

## The stages (in order)

```
push / PR
  ├─ backend   · ruff lint · pytest · alembic head + upgrade on real Postgres
  ├─ frontend  · tsc type-check · vite build
  ├─ e2e       · Playwright (needs frontend) → uploads an HTML report artifact
  ├─ security  · pip-audit · npm audit (high+) · gitleaks secret scan
  ├─ docker    · build backend + frontend images · Trivy image scan
  ├─ release   · main or v* tag → push images to GHCR (sha · latest · version)
  └─ deploy    · pull + roll out on the host · smoke test  (self-disabling)
```

## What each proves

| Job | Proves | Cost |
|-----|--------|------|
| **backend** | Code lints, unit tests pass, the Alembic chain resolves to exactly one head, and the migrations **actually apply** to a clean Postgres. | free (one PG service) |
| **frontend** | Types check and the SPA builds. | free |
| **e2e** | The app renders and behaves end-to-end — landing, entering the workspace, project listing, and the auth-config guard — with the **API mocked** (no Postgres/Redis/LLM keys). | free |
| **security** | No known-high npm advisory, no committed secret, Python CVEs surfaced. | free |
| **docker** | Both images build (lean backend, `INSTALL_ML=0`) and carry no fixable HIGH/CRITICAL CVEs. | free (GHA cache) |
| **release** | Immutable images in GHCR, tagged by commit SHA (plus `latest` on main and the version on a tag). | free (GHCR) |
| **deploy** | The released images are running on the host and `/health` answers 200. | free |

### Why the migration gate uses Postgres, not SQLite

SQLite accepts DDL that Postgres rejects. A SQLite-only check can pass a
migration that then breaks the deploy — and the deploy is exactly where the
entrypoint runs `alembic upgrade head`. The gate runs `alembic upgrade head`
against a real `postgres:16` service so the thing CI proves is the thing
production does.

### Blocking vs. advisory in the security job

- **Blocking:** `npm audit --audit-level=high` and **gitleaks**. A committed API
  key must stop the pipeline — that is what `.env.example` exists to prevent.
- **Advisory:** `pip-audit` and both Trivy image scans. A transitive CVE
  published upstream overnight must not wall off every merge to code that
  changed nothing; those arrive as Dependabot PRs (`.github/dependabot.yml`)
  where the fix is a version bump, which is the only real fix anyway.

> `gitleaks-action@v2` is free for personal accounts and public repos. If this
> repo is ever moved under a GitHub **organization**, that action requires a
> `GITLEAKS_LICENSE` secret — otherwise swap the step for the `gitleaks` CLI
> (`gitleaks detect --no-banner`), which has no such condition.

## E2E — why it's cheap and stakeholder-friendly

- **Playwright**, chosen for the lowest effort + a **visual HTML report** anyone
  can open (download the `playwright-report` artifact from the run).
- Runs against the **production build** (`npm run build:e2e`, which forces auth
  **off** via `.env.e2e` so results are deterministic regardless of a dev's local
  `.env`), served by `vite preview`.
- Each spec **mocks the backend** with `page.route(...)`, so no infrastructure or
  API keys are needed — it's free to run anywhere.
- Specs live in `frontend/e2e/*.spec.ts`; run locally with `npm run e2e`, then
  `npm run e2e:report` to open the report.
- Specs anchor on **structural class names** (`.vlp-proof-title`), not on visible
  copy. A text selector turns every marketing edit into a red pipeline, and a
  gate that goes red for reasons unrelated to correctness gets ignored.

## Release: what the tags mean

| Tag | Moves? | Use |
|-----|--------|-----|
| `:<commit-sha>` | never | **the deployable identity** — what deploy pins to, and what a rollback names |
| `:latest` | on every push to main | convenience for a dev pulling the tip |
| `:v1.2.3` | never | pushed when you `git tag v1.2.3 && git push --tags` |

Rollback is therefore "deploy the previous SHA", not "rebuild an old commit".

## Deploy (CD)

The deploy job is **self-disabling**: with no `DEPLOY_HOST` secret it writes a
note to the run summary and exits green, so CD stops at the registry until a host
exists. (A step that fails because nobody has chosen a host yet just teaches
everyone to ignore red.)

### Enabling it

Add these repository secrets (Settings → Secrets → Actions), and optionally a
`production` environment with required reviewers to gate the rollout:

| Secret | Meaning |
|--------|---------|
| `DEPLOY_HOST` | hostname/IP of the host running Docker Compose |
| `DEPLOY_USER` | SSH user (must be in the `docker` group) |
| `DEPLOY_SSH_KEY` | private key for that user |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -H <host>` — pinned, never `StrictHostKeyChecking=no` |
| `DEPLOY_PATH` | path to the repo checkout on the host |
| `DEPLOY_HEALTH_URL` | public `…/health` URL for the smoke test |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | baked into the frontend image at build time |

On the host, clone the repo once at `DEPLOY_PATH` and create `backend/.env` with
the runtime keys. The job then, per deploy: checks out the released commit,
`docker compose … pull`, `up -d`.

### What runs there

`deploy/docker-compose.prod.yml` overrides the base compose file to **run the
images CI built** instead of rebuilding on the host (`build: !reset null`, so a
host rebuild is impossible — the artifact serving users is the artifact the gates
passed). It also sets, per the production rules in `docs/MIGRATIONS.md`:

- `RUN_MIGRATIONS=1` on **`api` only** — two services racing `upgrade head` on
  one version table is a corruption, not a redundancy.
- `DB_AUTO_CREATE=false` everywhere — Alembic is the single source of truth.
- `AUTH_DISABLED=false` by default (the open-demo default is a local-only
  convenience).

Requires Compose **v2.24+** on the host for the `!reset` tag.

Manual deploy of a specific build:

```bash
GHCR_REPO=ghcr.io/<owner>/<repo> IMAGE_TAG=<sha> docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile app up -d
```

### Rollback

Re-run the workflow from the previous green commit, or on the host set
`IMAGE_TAG=<previous sha>` and re-run the compose command above. Migrations are
forward-only: a rollback that must also undo a schema change needs a new
migration, not a `downgrade` (see `docs/MIGRATIONS.md`).

## Other automation
- `.github/workflows/evals.yml` — the groundedness + retrieval eval gate (needs
  the stack + LLM keys; runs on demand / Mondays, not per-PR).
- `.github/dependabot.yml` — weekly grouped dependency PRs for pip and npm,
  monthly for Actions and base images.
