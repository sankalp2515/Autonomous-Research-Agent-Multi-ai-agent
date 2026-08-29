The graph is built in `app/agents/graph.py`; the node bodies live in
`app/agents/nodes.py`. Nine nodes, one bounded loop.

```diagram:pipeline
```

## Topology

```text
clarify → plan → evidence_schema → research → extract_evidence
        → report_architect → draft_sections → assemble → build_graph
              ↑                                    |
              +──────── bounded replan ────────────+
```

`clarify` has a conditional edge (a non-research ask exits early). `draft_sections` has a
conditional edge either forward to `assemble` or back to `plan` for one failing
sub-question, at most `SUBQUESTION_MAX_REPLANS` times.

---

## clarify

Rejects non-research asks with an intent guard, then decomposes the question into two to
five answerable sub-questions.

Decides **what must be investigated**. It does not decide how the result is communicated —
that is `report_architect`'s job, and the two are deliberately separate.

## plan

Produces source-specific search queries for arXiv and Semantic Scholar, informed by the
project's cross-session memory so a repeat question goes deeper rather than re-treading.

This is the node the replan edge returns to.

## evidence_schema

Derives a `ResearchEvidenceSchema` from the question, **before any paper is read**:

- the research **type** (which becomes the report genre);
- the **entities** under study;
- the **required** and optional comparison dimensions, each with its retrieval vocabulary
  — synonyms, metric tokens, section hints — and its `not_applicable_when` condition.

Generated, never hardcoded. But `normalized()` canonicalises the output and the call runs
at temperature 0, so the same question yields the same schema and two reports on that
question stay comparable. The node is idempotent across replans.

No schema means the extractor degrades to a legacy single-query read and **says so in the
coverage notes**. Pinned by `tests/test_evidence_schema.py`.

## research

Searches, screens and ingests.

**Screening ranks within each source pool and interleaves the pools** before cutting to
`SCREEN_MAX_CANDIDATES`. It must never sort all hits globally by `citation_count`:
`search_arxiv` cannot populate that field, so a global sort silently discards the entire
arXiv literature. Pinned by `tests/test_screening_pools.py`.

Ingestion downloads, parses (no page cap, per-section fallback on parser errors), chunks
with page and offset metadata, and embeds. Partial failures become honest **coverage
notes**, never silent gaps. Semantic Scholar hits with no open-access PDF but a known
arXiv id fall back to arXiv for full text.

## extract_evidence

The heaviest node, and the one that defines the product.

Each paper is read **on its own terms** into a `StudyRecord` — frameworks, baselines,
datasets, and findings tagged by comparison dimension. Retrieval runs **once per required
dimension** inside the document, with the window allocated round-robin across axes so no
axis starves the others.

Every finding still carries a `chunk_id` and a verbatim quote, still passes the gate, and
is still persisted as a real `Claim` plus `ClaimEvidence` row. The matrix **extends** the
grounding contract rather than opening a second, ungated rendering path.

Then `_recover_unresolved` re-reads every paper that left a required axis empty, batched
to one LLM call per paper, and `_attach_cells` records one of four states per
study × required dimension. Finally, deterministic synthesis computes what the *body* of
evidence supports.

Pinned by `tests/test_evidence_matrix.py`, `tests/test_dimension_retrieval.py`,
`tests/test_completeness_recovery.py`, `tests/test_synthesis.py`.

## report_architect

Decides how the result is **communicated** — and runs after the evidence matrix exists, so
it can see which dimensions recur across how many studies.

Sections need not mirror sub-questions. Each section's `sub_question` field holds the
**retrieval brief** in corpus vocabulary; the reader-facing question lives in `framing`.

The architect designs for a **genre** — comparison, decision, evolution, mechanism,
evaluation or survey. Genre spines are passed as *worked examples* beside the evidence,
never as templates to select and fill: the genre changes the question the architect
answers, not the answer. Genre comes from the evidence schema; an unknown value falls back
to comparison when two or more entities are under study, else survey. Temperature 0.

Pinned by `tests/test_report_architect.py`, `tests/test_gaps_and_genre.py`.

## draft_sections

Extracts 8–12 dense, source-diverse claims per section covering mechanisms, quantitative
results, comparisons, conditions, trade-offs and limitations, preferring claims that carry
a concrete number, effect size or benchmark. One distinct fact per claim; never restate.

Every claim then hits the **gate**. Failures regenerate with gate feedback up to
`SECTION_MAX_REGENS`, then trigger a bounded replan, then become an honest gap.

A single additional structure call reorganises verified claim indices into sub-themes and
comparison tables. **It never writes text** — layouts are validated against the claim set
before rendering.

## assemble

Deterministic. **No LLM.** Resolves citations against CrossRef, OpenAlex, arXiv or the
corpus, numbers footnotes in citation order from claim-to-chunk links, persists section
`framing` as the displayed subtitle, and writes the report.

The LLM never authors a `[N]` marker anywhere in the system. Numbering is generated at
render time.

## build_graph

Builds cross-source edges and writes an episodic memory of the run, so the next question
in this project starts from what this one learned.

## Budgets

| Setting | Default |
| --- | --- |
| `RUN_MAX_WALL_SECONDS` | 5400 |
| `RUN_MAX_LLM_CALLS` | 200 |
| `SECTION_MAX_REGENS` | 2 |
| `SUBQUESTION_MAX_REPLANS` | 1 |

`budget_reason()` names which budget ran out, so a wall-clock truncation is never
presented to the reader as an evidence gap.

## Checkpointing

Every node checkpoints full state to Postgres. An interrupted run resumes from the last
completed node rather than restarting.

## Related

- [The verification gate](#/docs/explanation/verification-gate)
- [Run a deep research run](#/docs/how-to/run-deep-research)
