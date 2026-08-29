Retrieval in Veriscope is not one system. It is three, aimed at three different questions,
and treating them as one is how coverage silently fails.

## Three retrieval problems

| Problem | Scope | Question |
| --- | --- | --- |
| Corpus retrieval | All project chunks | Which passages anywhere are relevant to this question? |
| Section retrieval | All project chunks, per section | Which passages support this section's brief? |
| **Dimension retrieval** | **One document** | Does *this paper* report *this axis*, and where? |

The third is the one that most systems do not have, and its absence is what produces a
matrix full of holes.

## Corpus and section retrieval

Hybrid: BM25 and dense vectors fused with reciprocal rank fusion (`RRF_K` 60), then
reranked by a local cross-encoder. `RETRIEVAL_TOP_K` is 12 for general retrieval;
`SECTION_TOP_K` is 20 with `SECTION_MAX_PER_DOC` capped at 3 so one paper cannot dominate
a section.

Query transformation and contextual compression sit around this in
`app/retrieval/query_transform.py` and `compress.py`.

## Dimension retrieval

```diagram:dimension
```

`app/retrieval/dimension.py` runs a **vocabulary-rich search for every required axis
inside one document** — BM25 over the schema's synonyms and metric tokens, a
document-scoped dense search, and numeric and section priors that favour results tables
and results sections. Then it allocates the paper's window **round-robin across axes**, so
no axis can starve the others.

### What it replaced

One generic objective query, taking the top 8 of a roughly 63-chunk paper. That left 30 of
100 matrix cells empty **while the evidence sat in the corpus**.

Measured on that corpus, retrieval recall on those cells went from **36.7% to 86.7%**.

### Why a bigger window would not have fixed it

A generic query ranks by generic relevance. The passage reporting latency in a paper about
accuracy scores poorly against an objective-level query no matter how many results you
take — you would need to take most of the paper before it surfaced, at which point you are
not retrieving, you are pasting.

The fix is aim, not volume. Do not answer a coverage complaint by raising a global
`top_k`; that buys more of the same badly-aimed ranking.
`tests/test_dimension_retrieval.py` pins this, including a fixture that reproduces the
original miss.

## The vocabulary comes from the schema

Each required dimension arrives from `evidence_schema` carrying its own retrieval
vocabulary — synonyms, metric tokens, section hints — plus a `not_applicable_when`
condition. This is why the schema is derived **before any paper is read**: retrieval needs
to know what it is looking for before it looks.

When no schema exists, the extractor degrades to the legacy single-query read and says so
in the coverage notes rather than pretending to full coverage.

## Screening is retrieval too

The step before all of this decides which papers exist at all.

`_screen_papers` ranks **within** each source pool — arXiv, Semantic Scholar — and
interleaves them before cutting to `SCREEN_MAX_CANDIDATES`. It must never sort all hits by
`citation_count`, because `search_arxiv` cannot populate that field, so a global sort
silently discards the entire arXiv literature. For most CS questions, that literature *is*
the field.

This was a real, shipped bug. `tests/test_screening_pools.py` pins it.

## The reranker's job, precisely

Relevance. Nothing else. It is never used as an entailment signal — see
[The verification gate](#/docs/explanation/verification-gate).

## Related

- [Tune retrieval](#/docs/how-to/tune-retrieval) — the operational procedure.
- [Pipeline nodes](#/docs/reference/pipeline-nodes)
