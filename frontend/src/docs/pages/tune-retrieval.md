Read this when the evidence matrix has holes you believe are wrong — cells marked
`extraction_uncertain` (or, worse, `not_reported`) for papers you know report the number.

:::danger Measure before and after, always
Never claim a retrieval improvement without both benchmarks below. Fill rate on its own is
not evidence of improvement — trading honesty for completeness must show up as a
regression, and `mislabeled_not_reported` is the metric that makes it visible.
:::

## Step 1 — establish where the evidence actually is

```bash
python -m evals.evidence_bench --report <report_id> --rerank
```

This measures **retrieval recall on cells whose evidence is genuinely in the corpus**. If
recall is already high and cells are still empty, the problem is extraction or the
schema, not retrieval — stop tuning retrieval.

## Step 2 — A/B the extraction layer

Run both arms over an already-ingested corpus, so the only variable is the extractor:

```bash
python -m evals.extraction_ab --report <report_id> --json new.json
```

```bash
python -m evals.extraction_ab --report <report_id> --legacy --json old.json
```

```bash
python -m evals.evidence_bench --report <report_id> --matrix new.json
```

## What the knobs actually do

```diagram:dimension
```

| Setting | Default | When to change it |
| --- | --- | --- |
| `EVIDENCE_CHUNKS_PER_DIMENSION` | 6 | An axis is consistently thin across many papers. |
| `EVIDENCE_MAX_CHUNKS_PER_PAPER` | 24 | Papers are long and many axes are required. |
| `EVIDENCE_DIMENSION_RERANK` | true | Turning it off is a debugging step, not a tuning step. |
| `EVIDENCE_MAX_DIMENSIONS` | 6 | The question genuinely has more required axes. |
| `RETRIEVAL_TOP_K` | 12 | Chat and general retrieval, **not** matrix extraction. |
| `SECTION_TOP_K` | 20 | Chunks offered to one section draft. |
| `SECTION_MAX_PER_DOC` | 3 | One paper is dominating a section. |
| `RRF_K` | 60 | Reciprocal-rank-fusion constant for BM25 + dense. |

:::warn Raising a global top_k is almost never the fix
The original failure mode was one generic objective query taking the top 8 of a ~63-chunk
paper — 30 of 100 matrix cells empty while the evidence sat in the corpus. Aiming
retrieval per axis moved recall on those cells from 36.7% to 86.7%. A bigger window would
simply have bought more of the same badly-aimed ranking.
:::

## If the schema is the problem

`evidence_schema` derives the required and optional comparison dimensions from the
question, each with its own retrieval vocabulary — synonyms, metric tokens, section hints
— and a `not_applicable_when` condition. If the vocabulary does not match how the papers
in your field actually write, retrieval cannot find the passages.

The schema is generated, never hardcoded, but `normalized()` canonicalises it and the call
runs at temperature 0, so the same question yields the same schema. If the vocabulary is
wrong, the leverage is in the **question phrasing** — use the terms the literature uses.

When no schema exists at all, the extractor degrades to the legacy single-query read and
**says so in the coverage notes** rather than pretending to full coverage.

## If retrieval is fine and cells are still empty

Then the honest answer is the one already on screen. `extraction_uncertain` means we could
not establish either way, and that is a true statement. Do not tune until the label flips
— a fabricated or contextless value is worse than a correctly labelled hole.

## Related

- [Cell states](#/docs/explanation/cell-states)
- [Evaluation](#/docs/reference/evals)
