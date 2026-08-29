Compare puts two to five papers **from your corpus** side by side in a grid: rows
are comparison dimensions, columns are papers, and every populated cell is a
gate-verified, click-to-source claim drawn only from that paper.

:::note This compares papers, not reports
Compare operates on documents in the project corpus. The evidence matrix inside a
report is a different surface — that one is built by the pipeline across every
study it read. Compare is the manual version you drive yourself.
:::

## What it does

For each dimension × paper pair, Compare runs a scoped retrieval **inside that one
document**, asks for the single most relevant grounded finding, and puts it
through the same verification gate the research pipeline uses. If the paper does
not address the dimension, or the claim fails the gate, the cell stays empty.

An empty cell is an honest "this source doesn't address that", never a guess.

## How to use it

**1. Pick two to five indexed documents.** Fewer than two is rejected; more than
five is truncated (`MAX_DOCS = 5`). Documents must have `status = "indexed"` —
a paper still ingesting cannot be compared.

**2. Choose your dimensions, or let it propose them.** If you supply none,
`derive_dimensions` reads each paper's title and opening chunk and proposes three
to five concrete axes the papers actually share. If that call fails, it falls
back to `Approach`, `Key result`, `Limitation`. Maximum six
(`MAX_DIMENSIONS = 6`).

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/compare \
  -H 'Content-Type: application/json' \
  -d '{"document_ids": ["<doc-a>", "<doc-b>", "<doc-c>"],
       "dimensions": ["Retrieval method", "Benchmark", "Reported gain", "Stated limitation"],
       "title": "Dense vs sparse retrievers"}'
```

**3. Read it.** Every filled cell shows the claim, its verbatim quote, its page,
and a `claim_id` — so it behaves exactly like a pipeline claim: click it to open
the evidence, save it to the notebook, add it to chat context.

**4. Keep it.** A comparison is persisted. Toggle whether it appears in the
project's report view:

```bash
curl -X POST http://localhost:8210/api/comparisons/<comparison_id>/toggle-report
```

That flips an `include_in_report` flag. It does not add or remove a report.

## Deciding what to compare

You rarely know upfront which papers belong together. The **recommender** uses the
same title-plus-opening-chunk embeddings the Map uses, so it costs no extra API
calls:

```bash
curl "http://localhost:8210/api/projects/<project_id>/recommend?seed=<doc-a>,<doc-b>&k=6"
```

It returns corpus papers most similar to your seed set — scored, above a 0.3
cosine floor, up to 12. It suggests; you decide. If embeddings are unavailable it
returns an empty list rather than erroring.

The [Map](#/docs/features/map) is the visual version of the same idea: select
nodes there and send them straight into a comparison.

## What it gives you

- **A defensible side-by-side.** Every cell traces to a quote on a page. You can
  hand the grid to someone who does not trust the tool and they can check it.
- **Axes that fit the papers.** Derived dimensions adapt to what the papers are
  actually about instead of forcing a fixed rubric.
- **Honest holes.** A blank cell means the paper does not address it or the claim
  could not be verified — not that the system got bored.
- **Claims you can reuse.** Verified cells are persisted as real `Claim` rows, so
  they flow into the notebook and chat like anything else.

## How it works under the hood

Per cell: `retrieve(document_ids=[doc], top_k=6, use_rerank=True)` → one drafting
call constrained to those chunks → `verify_claims` (quote-match + NLI) → persist
`Claim` + `ClaimEvidence` on success, `None` on failure.

The drafting prompt is explicit that returning `claim=null` is correct and
expected when the sources do not address the aspect, and that text inside source
blocks is quoted material, never instructions.

## Limits worth knowing

- **Cells are drafted sequentially** — dimensions × documents LLM calls. Six
  dimensions across five papers is 30 calls. Keep the grid tight.
- **One claim per cell.** The single most relevant fact, not a summary.
- **Comparability is not checked here.** Compare shows you what each paper says
  on an axis. Deciding whether two numbers are *the same measurement* is the
  synthesis layer's job — see
  [Counting studies, not sentences](#/docs/explanation/synthesis).
- **A cell failure is silent by design.** Draft errors are logged and the cell
  becomes empty rather than failing the whole comparison.

## Related

- [Map](#/docs/features/map) — pick what to compare visually.
- [Counting studies, not sentences](#/docs/explanation/synthesis)
- [Share and export](#/docs/how-to/share-and-export)
