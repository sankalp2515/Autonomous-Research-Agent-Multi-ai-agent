All endpoints are served under `/api`. In the Docker `app` profile the frontend proxies
`/api` to the backend, so the base URL is the same origin. From source the API listens on
`http://localhost:8210`.

## Authentication

When `AUTH_DISABLED=false`, send a Supabase access token:

```bash
curl http://localhost:8210/api/projects \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Tokens are verified against the Supabase project's JWKS endpoint (RS256/ES256), with the
legacy HS256 secret as a fallback. When `AUTH_DISABLED=true` the header is not required.

## Projects and organisations

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/projects` | List projects visible to the caller. |
| `POST` | `/api/projects` | Create a project. `201` |
| `GET` | `/api/orgs` | List organisations. |
| `POST` | `/api/orgs` | Create an organisation. `201` |
| `GET` | `/api/orgs/{org_id}/members` | List members. |
| `POST` | `/api/orgs/{org_id}/members` | Add a member. `201` |
| `PATCH` | `/api/orgs/{org_id}/members/{member_id}` | Change a member's role. |
| `DELETE` | `/api/orgs/{org_id}/members/{member_id}` | Remove a member. |
| `POST` | `/api/orgs/{org_id}/invites` | Create an invite. `201` |
| `GET` | `/api/orgs/{org_id}/invites` | List pending invites. |
| `DELETE` | `/api/orgs/{org_id}/invites/{invite_id}` | Revoke an invite. |
| `POST` | `/api/invites/accept` | Accept an invite. |

## Documents and corpus

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/documents` | List corpus documents. |
| `POST` | `/api/projects/{project_id}/documents` | Upload a PDF. `201` |
| `DELETE` | `/api/projects/{project_id}/documents/{document_id}` | Remove a source (leaves a tombstone). |
| `POST` | `/api/projects/{project_id}/import/bibtex` | Import a BibTeX library. `202`, runs in background. |

## Runs

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/pipeline` | Launch a research run. `202`, returns `run_id`. |
| `GET` | `/api/projects/{project_id}/runs` | List runs. |
| `GET` | `/api/status/{run_id}` | Poll run status, counters and the server-computed clock. |
| `GET` | `/api/status/{run_id}/stream` | **SSE** stream of typed progress events. |
| `GET` | `/api/projects/{project_id}/resume` | What is resumable. |
| `POST` | `/api/runs/{run_id}/resume` | Resume from the last checkpoint. `202` |
| `POST` | `/api/clarify` | Run the intent guard and sub-question decomposition alone. |
| `POST` | `/api/screen` | Search + rank + recommend keep/drop for every candidate, **without ingesting**. See [Screening](#/docs/features/screening). |

`POST /api/screen` takes `{project_id, query, since_year?, until_year?,
min_citations?}` and returns the derived `objective`, `field`, `in_scope`, the
resolved constraints, `found`, and a `candidates` array — each with `score`,
`recommend` (`keep` / `drop`) and a plain-language `reason`.

### Progress events

Every event carries a `kind` assigned **at the publish site**, plus running counters.
Clients group, filter and colour on `kind` alone — never by matching message text.

| `kind` | Meaning |
| --- | --- |
| `stage` | A graph node started or finished. |
| `search` | An external source query. |
| `ingest` | A document downloaded, parsed or chunked. |
| `corpus` | Corpus-level state change. |
| `extract` | Per-paper evidence extraction. |
| `recover` | The unresolved-cell recovery pass. |
| `verify` | A claim passed the gate. |
| `refuse` | A claim was refused. |
| `error` | A failure worth surfacing. |
| `done` | The run finished. |

## Reports

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/report/{report_id}` | Full report: sections, claims, matrix, funnel, dossier. |
| `GET` | `/api/report/{report_id}/metrics` | Grounding metrics. |
| `GET` | `/api/report/{report_id}/contradictions` | NLI-detected conflicts between claim pairs. |
| `GET` | `/api/report/{report_id}/next-questions` | Follow-ups derived from counted gaps. |
| `POST` | `/api/report/{report_id}/share` | Create a public read-only slug. `201` |
| `DELETE` | `/api/report/{report_id}/share` | Revoke the slug. |
| `GET` | `/api/shared/{slug}` | Fetch a shared report — **no auth**. |

## Chat, claims and evidence

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat` | Grounded Q&A over the project corpus. |
| `GET` | `/api/projects/{project_id}/answers` | Past answers. |
| `POST` | `/api/refind` | Re-run retrieval for a claim. |
| `GET` | `/api/claims/{claim_id}/evidence` | The full evidence chain for one claim. |

`POST /api/chat` takes `{project_id, question}` plus **one** optional scope, and
the scope it receives decides how the answer is persisted:

| Body field | Mode | Stored `kind` |
| --- | --- | --- |
| neither | whole corpus, guardrail runs first | `corpus` |
| `document_id` | one paper | `paper` |
| `entity_refs` (≤50 `{kind, id}`) | only the selected items, with their chunks seeded | `selection` |

Only `corpus` answers are restored as chat history. See
[Ask the corpus](#/docs/features/ask) and
[The + Chat button](#/docs/features/chat-context).

## Notebook, notes and memory

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` `POST` | `/api/projects/{project_id}/notebook` | List / save a verified claim by `claim_id`. Saving twice updates the note instead of duplicating. |
| `DELETE` | `/api/notebook/{saved_id}` | Unpin. The claim and its evidence are untouched. |
| `GET` `POST` | `/api/projects/{project_id}/notes` | List / create notes (`title`, `body`, `tags`, `source_ref`, `claim_id`). |
| `PATCH` `DELETE` | `/api/notes/{note_id}` | Edit / delete a note. |
| `GET` | `/api/projects/{project_id}/memory` | Everything the project remembers, newest first. |
| `GET` | `/api/projects/{project_id}/memory/recall` | Semantic recall for `?q=` (≥2 chars), `k` ≤ 20. Orientation only — never answer evidence. |
| `POST` | `/api/projects/{project_id}/memory` | Write a memory. `kind` ∈ `episodic` / `semantic` / `preference`. `201` |

## Monitoring

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/monitor` | Watches and outstanding alerts. **Seeds watches from the project's last completed run on first view.** |
| `POST` | `/api/projects/{project_id}/watches` | Create a watch. Query is 4–500 chars. `201` |
| `POST` | `/api/watches/{watch_id}/toggle` | Enable / disable. Only active watches are checked. |
| `POST` | `/api/projects/{project_id}/monitor/check` | Check every active watch against arXiv + Semantic Scholar. `202` |
| `POST` | `/api/alerts/{alert_id}/add` | Ingest the alerted paper into the corpus. |
| `POST` | `/api/alerts/{alert_id}/dismiss` | Dismiss the alert. |

Each check queries **both** sources per watch — arXiv sorted by `submittedDate`
(12 results) and Semantic Scholar by relevance (12) — then filters by identity,
prior alerts, corpus dedup, and a local embedding similarity of ≥ 0.42, keeping
at most 8 per watch. No LLM call. See [Monitor](#/docs/features/monitor).

## Analysis surfaces

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/dashboard` | Verification health, cost, latency, retrieval quality, provider health, run history. |
| `GET` | `/api/projects/{project_id}/map` | Similarity graph over corpus papers. Cached 30 min; `?refresh=true` recomputes. |
| `GET` | `/api/projects/{project_id}/recommend` | Corpus papers similar to a seed set. Requires `?seed=<doc-id>,<doc-id>`; `k` ≤ 12. Empty `seed` returns `[]`. |
| `GET` | `/api/graph/{project_id}` | Persisted knowledge graph nodes and edges. |
| `POST` | `/api/projects/{project_id}/compare` | Create a comparison from `{document_ids, dimensions?, title?}`. 2–5 documents, ≤6 dimensions. `201` |
| `GET` | `/api/projects/{project_id}/comparisons` | List comparisons. |
| `GET` | `/api/comparisons/{comparison_id}` | Fetch one, with its full matrix. |
| `POST` | `/api/comparisons/{comparison_id}/toggle-report` | Flip the `include_in_report` flag. |
| `DELETE` | `/api/comparisons/{comparison_id}` | Delete. |

:::warn Compare takes documents, not reports
`document_ids` are corpus documents with `status = "indexed"`. Fewer than two is
a validation error; more than five is truncated. See
[Compare papers](#/docs/features/compare).
:::

## Status codes

| Code | Meaning here |
| --- | --- |
| `202` | Accepted for background processing — poll or stream for the outcome. |
| `401` | Missing or invalid token while auth is enabled. |
| `429` | Rate limit — see `RATE_LIMIT_PER_MIN` and `PIPELINE_RATE_LIMIT_PER_MIN`. |
| `503` | Deliberate load shedding above `MAX_QUEUE_DEPTH`. |

## Related

- [Configuration](#/docs/reference/configuration)
- [Pipeline nodes](#/docs/reference/pipeline-nodes)
