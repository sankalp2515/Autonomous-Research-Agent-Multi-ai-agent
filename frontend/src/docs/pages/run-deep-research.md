This is the reference procedure for launching and steering a run, including the settings
that change its behaviour. For a guided first pass, read
[Your first verified report](#/docs/tutorials/first-report) instead.

## Launch a run

From the UI: open a project, enter the question, start. From the API:

```bash
curl -X POST http://localhost:8210/api/pipeline \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "<uuid>", "query": "How do dense and sparse retrievers compare on multi-hop QA?"}'
```

The endpoint returns `202` with a `run_id`. Stream progress from
`GET /api/status/{run_id}/stream` (SSE) or poll `GET /api/status/{run_id}`.

## Steer the sourcing

| Setting | Default | Effect |
| --- | --- | --- |
| `SCREEN_MAX_CANDIDATES` | 50 | How many screened candidates survive to eligibility. |
| `RESEARCH_MAX_PAPERS` | 28 | Hard cap on papers ingested into the corpus for one run. |
| `CITATION_WEIGHT` | 0.15 | Weight of citation count in screening rank. |
| `RECENCY_WEIGHT` | 0.20 | Weight of recency. |
| `RECENCY_HORIZON_YEARS` | 15 | How far back "recent" reaches. |

:::danger Never sort all hits globally by citation count
Screening ranks **within** each source pool and interleaves before cutting. `search_arxiv`
cannot populate `citation_count`, so a global sort silently discards the entire arXiv
literature — which for most CS questions *is* the field. This was a real shipped bug;
`tests/test_screening_pools.py` pins it.
:::

## Steer the extraction

Extraction is where a run spends most of its time and most of its value. Each paper is
read on its own terms into a `StudyRecord`, and searched once **per required dimension**.

| Setting | Default | Effect |
| --- | --- | --- |
| `EVIDENCE_MAX_PAPERS` | 22 | Papers the extractor will read. |
| `EVIDENCE_EXTRACT_CONCURRENCY` | 4 | Papers extracted per wave. |
| `EVIDENCE_DIMENSION_RETRIEVAL` | true | Kill switch back to the legacy single-query path. |
| `EVIDENCE_CHUNKS_PER_DIMENSION` | 6 | Ceiling per axis, before dedup. |
| `EVIDENCE_MAX_CHUNKS_PER_PAPER` | 24 | Total window, allocated round-robin across axes. |
| `EVIDENCE_MAX_DIMENSIONS` | 6 | Columns the matrix can carry. |

```diagram:dimension
```

:::warn Do not "fix" thin coverage by raising a global top_k
That buys more of the same badly-aimed ranking. The fix is aiming retrieval at the axis
that is empty — which is exactly what per-dimension retrieval and the recovery pass do.
:::

## Steer the recovery pass

After first-pass extraction, every paper that left a **required** axis empty is re-read
with retrieval aimed at exactly those axes — batched to one LLM call per paper.

| Setting | Default | Effect |
| --- | --- | --- |
| `EVIDENCE_RECOVERY_ENABLED` | true | Disabling it pushes empty cells to `extraction_uncertain`, never to `not_reported`. |
| `EVIDENCE_RECOVERY_MAX_PAPERS` | 24 | Cap on papers re-read. |
| `EVIDENCE_ABSENCE_MIN_QUERIES` | 2 | Distinct queries required before an absence may be called. |
| `EVIDENCE_ABSENCE_MIN_CHUNKS` | 4 | Passages that must have been examined. |

The last two implement the rule that must never be relaxed: `not_reported` requires
**evidence of search**. See [Cell states](#/docs/explanation/cell-states).

## Steer the budgets

A real corpus of roughly 28 papers plus per-paper extraction needs room:

| Setting | Default | Notes |
| --- | --- | --- |
| `RUN_MAX_WALL_SECONDS` | 5400 | At the old 1800 the last sections closed as "budget exhausted" gaps while only 11 of 150 calls had been spent. |
| `RUN_MAX_LLM_CALLS` | 200 | |
| `SECTION_MAX_REGENS` | 2 | Gate-failure retries per section. |
| `SUBQUESTION_MAX_REPLANS` | 1 | Bounded loop back to `plan`. |

When a run stops on budget, `budget_reason()` names **which** budget ran out — so a
wall-clock truncation is never presented to the reader as an evidence gap.

## Resume an interrupted run

Every node checkpoints full state.

```bash
curl -X POST http://localhost:8210/api/runs/<run_id>/resume
```

`GET /api/projects/{project_id}/resume` reports what is resumable.

## Control concurrency

| Setting | Default | Effect |
| --- | --- | --- |
| `MAX_CONCURRENT_RUNS_PER_PROJECT` | 2 | Per-project admission cap. |
| `MAX_QUEUE_DEPTH` | 200 | Global shed threshold — above it the API returns 503. |
| `PIPELINE_RATE_LIMIT_PER_MIN` | 10 | Run launches per minute. |

## Related

- [Pipeline nodes](#/docs/reference/pipeline-nodes) — what each stage actually does.
- [Configuration](#/docs/reference/configuration) — every setting.
- [Tune retrieval](#/docs/how-to/tune-retrieval) — when coverage is genuinely thin.
