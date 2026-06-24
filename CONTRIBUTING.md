# Contributing to Veriscope

Thanks for your interest! Veriscope is a verification-first research assistant —
the golden rule is: **nothing the user sees may be ungrounded.** Keep that
invariant intact and most decisions follow.

## Getting set up

See the [Quick start](README.md#quick-start-local). In short: `docker compose up -d`,
create `backend/.env`, install the backend (`pip install -e ".[ml]" -e ".[dev]"`),
run the API + one worker, and `npm install && npm run dev` in `frontend/`.

## Before opening a PR

```bash
cd backend && pytest                # all unit tests must pass
cd backend && ruff check app        # lint (kept clean)
cd frontend && npm run build        # type-check + build must pass
```

CI runs these on every push. The groundedness eval gate
(`.github/workflows/evals.yml`) runs on schedule/manually and must not regress.

## Ground rules

1. **Never bypass the verification gate.** Any path that surfaces a claim to the
   user must go through quote-match + (when available) NLI entailment. If you add
   a new generation surface, route it through `app/verification/gate.py`.
2. **Don't mix evidence classes.** Scholarly (papers) and practitioner (repos/blogs)
   sources stay separated in retrieval, drafting and the UI.
3. **Fail open on observability, fail closed on trust.** Tracing/metrics/auth-optional
   features must never break a request; verification must never be skipped silently.
4. **Free-tier friendly.** Prefer local/deterministic approaches; new LLM steps go
   through `app/llm/router.py` (throttled, cached, fallback-chained) and add a route
   entry keyed by task complexity.
5. **Match the surrounding style** — comment density, naming, and idioms.

## Where things live

| Area | Path |
|---|---|
| Pipeline nodes / agents | `backend/app/agents/` |
| Verification | `backend/app/verification/` |
| Retrieval (RAG) | `backend/app/retrieval/` |
| Services (chat, mapping, monitor, analysis) | `backend/app/services/` |
| API routes | `backend/app/api/routes.py` |
| Frontend views | `frontend/src/components/` |
| Eval harness | `backend/evals/` |

## Commit / PR

- Small, focused PRs with a clear description of the change and why.
- Reference the issue you're addressing.
- Add or update tests for behaviour changes (especially anything trust-critical).

## Reporting bugs / ideas

Open an issue with steps to reproduce (and the last ~15 lines of the worker log
for pipeline issues — the heartbeat + per-call timings make most failures obvious).
