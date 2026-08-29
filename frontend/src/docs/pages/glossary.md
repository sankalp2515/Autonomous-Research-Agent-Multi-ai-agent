Terms used precisely throughout Veriscope and these docs.

## Core objects

**Chunk** — the addressable unit of a document: text plus `document_id`, `section`, `page`,
`char_start` and `char_end`. Every quote resolves to a span inside exactly one chunk.

**Claim** — one distinct fact, with a status of `verified`, `failed` or `gap`. The report
renders only `verified` rows.

**Claim evidence** — the persisted verdict for a claim: the `chunk_id`, the verbatim
`quote`, `quote_match_ok`, `nli_label` and `nli_score`. This is what the evidence rail
displays.

**Citation** — a resolved reference, carrying its resolver (`corpus`, `crossref`,
`openalex`, `arxiv`) and `verified_at`. References render only from these rows.

**StudyRecord** — one paper read on its own terms: frameworks, baselines, datasets, and
findings tagged by comparison dimension. The unit of evidence is the study, not the chunk.

## The gate

**Quote match** — layer 2. The claim's quote must exist verbatim inside the cited chunk.
`QUOTE_FUZZY_THRESHOLD` absorbs PDF-extraction artefacts only, never paraphrase.

**Entailment / NLI** — layer 3. The claim must follow from the chunk under a local
DeBERTa-class model. A **faithfulness** signal, not an evidence-strength signal.

**Refusal** — a first-class answer state. The corpus does not support this, stated plainly.

**Honest gap** — a section that could not be verified, labelled as such rather than
softened.

## The evidence matrix

**Comparison dimension** — an axis the question requires studies to be compared on.
Declared by `evidence_schema` before any paper is read.

**Cell state** — `reported`, `not_reported`, `not_applicable` or `extraction_uncertain`.
The first three are facts about the study; the fourth is a fact about Veriscope.

**Evidence of search** — the precondition for `not_reported`: full text in hand, at least
`EVIDENCE_ABSENCE_MIN_QUERIES` distinct queries, at least `EVIDENCE_ABSENCE_MIN_CHUNKS`
passages examined.

**Recovery pass** — the second read of papers that left a required axis empty, aimed at
exactly those axes, one LLM call per paper.

## Synthesis

**Comparable** — two measurements match only if dimension, metric, dataset, task and unit
all match. Unknown context never counts as matching.

**Contradiction candidate** — comparable numbers differing by more than 10%, or more than
2 percentage points on percentage axes.

**Explained by conditions** — a contradiction candidate where the studies recorded
different baseline, model or condition.

**Evidence strength** — a study count, not a score. `strongly_supported` needs ≥5
independent studies and ≥3 measuring it the same way. Every class carries a `basis`.

**Gap kinds** — `under_measured`, `single_study`, `no_comparable_evidence`, `contested`.
Each carries a `basis` naming its counts.

## Pipeline

**Evidence schema** — the derived statement of what the question requires: research type,
entities, required and optional dimensions with retrieval vocabulary. Temperature 0,
canonicalised, idempotent across replans.

**Genre** — comparison, decision, evolution, mechanism, evaluation or survey. Shapes what
the architect designs. Genre spines are worked examples, never templates.

**Retrieval brief** — a section's `sub_question` field: corpus vocabulary aimed at
retrieval. The reader-facing question lives in `framing`.

**Bounded replan** — one conditional edge back to `plan` for a failing sub-question, at
most `SUBQUESTION_MAX_REPLANS` times.

**Budget reason** — which budget ran out. Never presented to the reader as an evidence gap.

**Checkpoint** — full state persisted after every node, so an interrupted run resumes.

## Corpus

**Funnel ladder** — discovered → screened → eligible → ingested → full_text_available →
extracted → included_in_synthesis → cited.

**Excluded by reason** — why each paper left the funnel. Never collapsed into one number.

**Abstract-only** — a document with no retrievable full text. Cannot ground an absence.

**Tombstone** — the auditable record left when a source is removed, so previously cited
claims stay traceable.

**Hot / cold tier** — embedded vectors capped by `CORPUS_MAX_EMBEDDED_CHUNKS`; text and
verified claims in Postgres forever. Chunks backing verified claims are never evicted.

**Evidence class** — scholarly (paper, upload) versus practitioner (repo, blog). They never
share a drafting context.

## Interface

**Evidence rail** — the persistent side panel pinning a quoted span, its stamp and its
source passage. Never a modal.

**Provenance chain** — sentence → verdict → span → passage → document.

**Dossier** — the four-face panel: Sample, Evidence, Gaps, Methods.

**Sections grounded** — the report gauge. A fact about the report, not about the field.

**Event kind** — the type assigned to a progress event at its publish site: `stage`,
`search`, `ingest`, `corpus`, `extract`, `recover`, `verify`, `refuse`, `error`, `done`.

## Guarantees

**G1** every claim traces to a source span · **G2** zero fabricated citations · **G3**
closed corpus by default · **G4** refusal over fabrication · **G5** honest gaps.
