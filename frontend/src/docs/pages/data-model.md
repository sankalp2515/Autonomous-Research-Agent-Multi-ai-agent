Postgres is the system of record. Qdrant holds vectors keyed by `chunk_id` and is
rebuildable. Redis holds nothing that cannot be reconstructed.

```diagram:data-model
```

## The grounding chain

Four tables carry G1 and G2 between them. Read them as one sentence: *a claim points at a
chunk, through evidence that records the verbatim quote and both verdicts, and renders a
reference only if a citation row resolved.*

| Table | Key columns | Why it exists |
| --- | --- | --- |
| `chunks` | `document_id`, `section`, `page`, `char_start`, `char_end`, `text` | The addressable unit. Every quote resolves to a span inside one of these. |
| `claims` | `text`, `report_id` / `answer_id`, `status` | `verified` / `failed` / `gap`. The report renders **only** verified rows. |
| `claim_evidence` | `claim_id`, `chunk_id`, `quote`, `quote_match_ok`, `nli_label`, `nli_score` | The gate's verdict, persisted. This is what the evidence rail displays. |
| `citations` | resolved identifier, `resolver`, `verified_at` | `corpus` / `crossref` / `openalex` / `arxiv`. A fabricated citation has no row, so it cannot render. |

## Corpus tables

| Table | Notes |
| --- | --- |
| `projects` | The workspace and the unit of corpus isolation. RLS per user. |
| `documents` | `source_type`: `paper` / `repo` / `blog`. Dedup keys: `sha256`, then `doi` / `arxiv_id`, then fuzzy title + authors. Preprint and published versions are **linked as versions, not collapsed**. |
| `chunks` | Embeddings live in Qdrant under the same `chunk_id`. |

## Run and output tables

| Table | Notes |
| --- | --- |
| `runs` | Pipeline executions: plan JSON, per-node status, budgets spent, checkpoint state. |
| `reports` | Sections; `confidence.plan` holds the persisted analysis plan as JSON — no migration needed to render it. |
| `answers` | Grounded chat responses, linked to their claims. |
| `graph_nodes` / `graph_edges` | Persisted `build_graph` output. Redis only ever caches this. |
| `audit_log` | Provenance of actions. |
| `feedback` | User signal on claims and reports. |

## Retention tiers

| Tier | Contents | Lifetime |
| --- | --- | --- |
| Global index | External scholarly APIs | Never duplicated locally |
| Hot | Embedded vectors for the working set | Capped by `CORPUS_MAX_EMBEDDED_CHUNKS` |
| Cold | Text, verified claims, quotes in Postgres | Forever — kilobytes per paper |

Evicted vectors rebuild on demand via the reindex job. **Chunks backing verified claims
are never evicted** — a published claim must never lose the ability to prove itself.

## Deletion semantics

Removing a source writes an auditable **tombstone** rather than cascading a hard delete.
Claims cited before the removal stay traceable; the reader sees that the source was
withdrawn rather than encountering a dangling reference.

## Invariants worth testing against

- A `claims` row with `status = verified` and no `claim_evidence` row is a bug.
- A rendered reference with no `citations` row is impossible by construction — if you can
  produce one, that is a G2 violation.
- A `claim_evidence` row whose `quote` is not a substring of its chunk's `text` (within
  `QUOTE_FUZZY_THRESHOLD`) should never have been written.
- Any Redis key whose loss changes what a user sees is misplaced state.

## Related

- [The grounding contract](#/docs/explanation/grounding-contract)
- [API reference](#/docs/reference/api)
