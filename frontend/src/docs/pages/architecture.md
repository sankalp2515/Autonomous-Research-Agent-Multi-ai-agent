This page is the map. It is deliberately short — each box links to the page that explains
it properly.

## The custody rule

Veriscope keeps state in three places, and the rule about which is authoritative is the
single most important architectural fact about the system:

| Store | Role | Rebuildable? |
| --- | --- | --- |
| **Postgres** | Durable truth — documents, chunks, claims, evidence, citations, runs. | No. This is the system of record. |
| **Qdrant** | Vectors keyed by `chunk_id`, plus the BM25 corpus. | Yes — reindex from Postgres. |
| **Redis** | Progress events, throttle buckets, LLM cache, run locks. | Yes — entirely disposable. |

Anything held in Redis must be reconstructable from Postgres and Qdrant. Nothing the user
sees is ever rendered from Redis alone.

```diagram:system
```

## The pipeline

A run is a LangGraph state machine of nine nodes with one bounded loop back to `plan`.
Every node checkpoints its full state, so an interrupted run resumes rather than restarts.

```diagram:pipeline
```

Five properties of that ordering are load-bearing and must not be collapsed:

1. **Sourcing before everything.** Screening ranks *within* each source pool and
   interleaves the pools, because a global sort by citation count silently discards the
   entire arXiv literature — arXiv search cannot populate that field.
2. **The unit of evidence is the study, not the chunk.** Each paper is read on its own
   terms into a `StudyRecord`.
3. **What the question requires is declared before any paper is read** — that is the
   `evidence_schema` node.
4. **Each paper is searched once per dimension**, not once per paper.
5. **Research planning is not report planning.** `clarify` decides what to investigate;
   `report_architect` decides how to communicate it, and runs *after* the evidence exists.

Full detail: [Pipeline nodes](#/docs/reference/pipeline-nodes).

## The gate

Three deterministic layers stand between a drafted sentence and the reader. The gate
**decides** — it never merely observes and reports a score afterwards.

```diagram:gate
```

Full detail: [The verification gate](#/docs/explanation/verification-gate).

## The data model

```diagram:data-model
```

Full detail: [Data model](#/docs/reference/data-model).

## The frontend

A React 18 + Vite single-page app with hash routing. Three surfaces carry the identity:

- **The report** — multi-level structure, comparison tables, metric callouts, inline
  footnotes and a Works Cited appendix.
- **The evidence rail** — clicking any citation pins the exact quoted span, its NLI stamp
  and the source passage beside the reading column. Never a modal.
- **The live run** — typed progress events, a server-computed clock, and a feed that
  keeps the whole run rather than the last six lines.

```diagram:report-anatomy
```

Full detail: [Design system](#/docs/explanation/design-system).

## Stack

| Layer | Choice |
| --- | --- |
| API | FastAPI |
| Orchestration | LangGraph |
| Vector store | Qdrant (vectors + BM25) |
| System of record | Postgres, Supabase-compatible, RLS per user |
| Cache / queue | Redis |
| PDF parse | pymupdf4llm |
| Embeddings | `BAAI/bge-small-en-v1.5`, local |
| Rerank | `cross-encoder/ms-marco-MiniLM-L-6-v2`, local — relevance only, never entailment |
| Entailment | `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, local |
| LLMs | Gemini, Groq, DeepSeek, OpenRouter — complexity-routed, free tiers |
| External search | arXiv, Semantic Scholar, GitHub, whitelisted blogs |
