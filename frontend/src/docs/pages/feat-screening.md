Screening is the human-in-the-loop step before a run. It searches, ranks and
recommends — and shows you **every** candidate with a plain-language reason — but
ingests nothing. You approve exactly what enters the corpus.

## Why it exists

Downloading and parsing a PDF is the expensive step, roughly 30–45 seconds each.
Screening happens on **title and abstract only, before any download**, so you cut
the set down while cutting is still cheap.

It is also the transparent "why these sources?" surface. The full funnel is
visible and **you**, not a hidden cap, decide what survives it.

## What it does

```text
your question
   → clarify: field, objective, 3–5 sub-questions, constraints
   → search arXiv + Semantic Scholar for each (up to 5 queries, both sources)
   → dedup by arxiv_id / doi / lowercased title, keeping the higher citation count
   → rank by citation count, then year → top 40
   → relevance screen: one LLM pass over all candidates
   → keep/drop recommendation + reason for every candidate
```

Nothing is ingested. The response is a list you act on.

## Constraints are parsed from your question

The clarify step reads constraints out of natural language, and the UI's chips can
also set them. **Whichever bound is tighter wins** — the caller is authoritative,
the parsed value is a backstop.

| You write | Parsed as |
| --- | --- |
| "2024–2026" | `since_year=2024`, `until_year=2026` |
| "after 2022" | `since_year=2022` |
| "before 2020" | `until_year=2020` |
| "at least 50 citations" | `min_citations=50` |

It also sets `in_scope=false` when the question is really biomedicine,
neuroscience, psychology, social science, humanities, medicine or law — this
platform searches arXiv and Semantic Scholar, which is computer science and
engineering territory. That is a warning, not a block.

## How a recommendation is decided

Every candidate gets `keep` or `drop` plus a reason, evaluated in this order:

1. **Outside the year window** → `drop`, *"published 2019 — outside the 2022–now window"*
2. **Below the citation floor** → `drop`, *"only 3 citations — below the 50 minimum"*
3. **Not relevant, or relevance score < 0.5** → `drop`, with the model's one-line
   reason, typically *"shares keywords but is off-subject"*
4. **Otherwise** → `keep`

If the relevance pass fails entirely, every candidate defaults to
`(relevant, 0.5, "")` — so a provider outage degrades to "recommend everything"
rather than silently dropping the field.

## How to use it

```bash
curl -X POST http://localhost:8210/api/screen \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "<uuid>",
       "query": "How do dense and sparse retrievers compare on multi-hop QA?",
       "since_year": 2022, "min_citations": 10}'
```

The response carries the derived `objective`, `field`, `in_scope`, the resolved
constraint values, how many raw hits were `found`, and the `candidates` array —
each with title, abstract (600 chars), authors, year, venue, citation count,
URLs, `score`, `recommend` and `reason`.

**In the UI:** everything recommended `keep` is pre-selected. Rows recommended
`drop` are dimmed but still selectable — the recommendation is advice, not a
filter. Adjust the selection, then launch the run with it.

**Read the drops, not just the keeps.** The reason text is where you catch a
mis-parsed constraint or a field mismatch before it costs you a 40-minute run.

## What it gives you

- **You see the whole funnel.** Not a summary of what survived — every candidate,
  with why.
- **You spend PDF-parsing time deliberately.** A 28-paper corpus you chose beats a
  28-paper corpus a cap chose.
- **Constraints are visible before they bite.** If "after 2022" was misread, you
  find out here, not in the report's year span.
- **A cheap dry run.** One clarify call plus one screening call. If the candidates
  look wrong, rephrase and screen again — you have spent seconds, not an hour.

## Limits worth knowing

- **Top 40 candidates** (`max_candidates`), from up to 5 queries per source.
- **Citation counts come from Semantic Scholar.** arXiv cannot populate them, so
  an arXiv-only preprint shows 0 — a citation floor will drop recent preprints
  that are genuinely relevant. This is the same asymmetry that makes global
  citation-sorting a bug in the pipeline; see
  [Three retrieval problems](#/docs/explanation/retrieval-design).
- **Dedup keeps the higher citation count**, which means the published version
  usually wins over the preprint at this stage.
- **Screening does not run automatically inside a pipeline run.** The pipeline has
  its own `_screen_papers` step with pool-aware ranking. This endpoint is the
  interactive surface.

## Related

- [Run a deep research run](#/docs/how-to/run-deep-research)
- [The research funnel](#/docs/explanation/funnel)
- [Monitor](#/docs/features/monitor) — the same approval principle, applied continuously.
