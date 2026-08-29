Every literature review is a funnel. Most tools report one number for it — "reviewed 28
papers" — and that number hides the only information a careful reader wants.

```diagram:funnel
```

## The ladder

`funnel.ladder` reports eight rungs, and they are never collapsed:

| Rung | What it counts |
| --- | --- |
| `discovered` | Everything the searches returned. |
| `screened` | Ranked within each source pool, then interleaved. |
| `eligible` | Passed the citation floor and year window. |
| `ingested` | Downloaded, parsed, chunked, embedded. |
| `full_text_available` | Not abstract-only, not paywalled. |
| `extracted` | A `StudyRecord` was produced. |
| `included_in_synthesis` | Contributed a comparable measurement. |
| `cited` | Appears in the finished report. |

## Why they cannot be one number

`excluded_by_reason` names why every paper that left the funnel left it: screened out,
citation floor, year window, over the ingest cap, no retrievable text, abstract-only,
extraction failed.

A paper rejected as off-topic, a paywalled PDF, and a paper the extractor could not read
are **three different facts about how far this review can be trusted**:

- *off-topic* says the search worked and the paper was irrelevant;
- *paywalled* says the field's evidence is partly inaccessible to this review, and might
  be systematically so;
- *extraction failed* says the tool fell short on material it had.

A single "28 papers reviewed" makes all three look identical. The second and third should
change how much weight a reader puts on the conclusion; the first should not.

## "Sections grounded", not "Coverage"

The report's gauge reads **Sections grounded**. It says every section found evidence it
could verify — a fact about the report.

It used to read "Coverage", and "6/6 sections grounded" was being read as "100% literature
coverage". Those are wildly different statements, and the second one is not something this
system can honestly assert about any field. The label was renamed to stop that misreading;
do not relabel it back.

## The methods panel

The report's methods block is the audit layer the report previously lacked — it verified
itself sentence by sentence while saying nothing about how its corpus was chosen.

It shows found → screened → ingested → extracted → cited, plus **what was refused**:
screened out, extraction refused, claims refused, filler dropped. These are real tallies
recorded by the pipeline in `state["funnel"]`.

A stage with no recorded count is **omitted rather than shown as zero**. Zero is an
assertion; absence of a count is not.

## The related principle

The funnel is the corpus-level version of what cell states are at the measurement level
and what gaps are at the synthesis level. All three answer the same question: *is this
statement about the world, or about us?*

`tests/test_research_funnel.py` pins the ladder and the exclusion reasons.

## Related

- [Cell states](#/docs/explanation/cell-states)
- [Counting studies, not sentences](#/docs/explanation/synthesis)
