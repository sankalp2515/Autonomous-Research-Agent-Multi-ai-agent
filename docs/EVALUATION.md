# Evaluation & tracing stack

How we know the system works, and how we watch it in production. Layered so each
piece has one job and the hard gates never depend on a soft (LLM-judge) signal.

## Offline evals (`backend/evals/`, CI: `.github/workflows/evals.yml`)

| Harness | Scope | Gate |
|---|---|---|
| `run_evals.py` | **Chat** groundedness on the golden set | HARD — fabricated_citations=0, support≥0.98, refusal≥0.95 |
| `run_report_evals.py` | **Report pipeline** (draft→gate→assemble) | HARD — fabricated_evidence=0, closed-corpus, no contradictions, honest gaps, answered≥0.8 |
| `calibrate.py` | Verification-gate **threshold calibration** vs a labeled boundary set | INFORMATIONAL — reports false-accept/false-reject + sweeps (see docs/CALIBRATION.md) |
| `run_ragas.py` | **RAGAS second opinion** (faithfulness, answer-relevancy, context precision/recall) | INFORMATIONAL — soft floors only |

**Why bespoke gates AND RAGAS:** the bespoke metrics are derived from the same
deterministic evidence the gate produces (quote-match + NLI), so they're
auditable and cheap — they own the release gate. RAGAS is LLM-judge-backed: an
*independent* cross-check that catches what the bespoke metrics might miss and
gives an industry-recognized number. It runs OFFLINE only (judge cost/latency
never touches the request path). RAGAS is wired to Groq (OpenAI-compatible judge)
+ the local BGE embeddings — we don't depend on OpenAI.

Install RAGAS: `pip install -e ".[ml,ragas]"`, then `python -m evals.run_ragas`.

## Research-synthesis benchmarks (human gold labels, not ours)

The harnesses above prove the pipeline does not fabricate. They do not prove the
research is RIGHT — that the corpus is the one a systematic reviewer would have
built, and that "verified" means what an expert would mean by it. These do, by
scoring the production code against labels written by people outside this
project. Every rate carries n and a 95% Wilson interval (`evals/stats.py`);
none is folded into a single score.

| Harness | Question | Gold | Cost |
|---|---|---|---|
| `scifact_gate.py` | When the gate says *verified*, would an expert agree the abstract supports the claim? | SciFact (Wadden et al., EMNLP 2020), CC BY-NC 2.0: expert claims x PubMed abstracts, SUPPORT / CONTRADICT / NEI | local NLI only, ~13 min, no LLM calls |
| `screening_bench.py` | Applying a published review's own criteria to its own candidate pool, does our screen include what the reviewers included? | SYNERGY Hall_2012 (CC0): 8,793 records, 104 included, criteria from the review's Table 2 (`evals/protocols/hall_2012.json`) | ~21 LLM calls per run |
| `report_integrity.py` | Does a finished report keep every promise it makes (PRISMA arithmetic, cell-state rules, quote spans, reproducible D sentences, citable references)? | the report's own claims | none (deterministic) |
| `reproducibility.py` | Asked twice, how much of the review survives (corpus, schema, cells, values, D sentences)? | the first run | two pipeline runs |

Data is fetched once into `evals/data/` (gitignored: SciFact is non-commercial
and SYNERGY abstracts may not be republished in plaintext). Outputs go to
`evals/out/` (gitignored). Pure logic is unit-tested without the data:
`tests/test_eval_harnesses.py`, `tests/test_report_integrity.py`.

### Current results (2026-11-25)

**Screening vs the Hall 2012 review** — all 104 included records + 200 sampled
excludes, Gemini behind the production router.

| | before (shipped code) | after F42-F45 (two runs) |
|---|---|---|
| recall on the reviewers' included studies | 50/104 = **48.1%** [38.7, 57.6] | 96/104 = **92.3%** [85.5, 96.0] · 95/104 = 91.3% [84.4, 95.4] |
| specificity (sampled excludes) | 199/200 = 99.5% | 200/200 = 100% [98.1, 100] · 198/200 = 99.0% [96.4, 99.7] |
| records never assessed | 120 (no verdict 78, failed call 42) | **0** |
| verdicts applied to the wrong paper | 4 | 0 (ignored and counted) |

Before the fixes only 7 of the 54 misses were the model disagreeing with the
reviewers; the rest were Veriscope failing to assess the paper and the funnel
calling it "screened out". After them every miss is a judgement call, and
several fall under the review's own written exclusions (reliability modelling,
fault localisation), which suggests label noise we have not adjudicated. The
conventional target in screening automation is 95% recall (the R in WSS@95,
Cohen et al. 2006): **we are near it, not at it.** Precision is not yet
quotable: with 200 negatives its floor at the true 1.2% prevalence is 23-37%
(H19).

Caveats that travel with these numbers: labels are FINAL inclusions (some are
only identifiable from full text, so 100% from abstracts is not attainable);
SYNERGY's set is 104 studies while the review reports 208; one review, one
field.

**Gate vs SciFact** — held-out dev split, shipped thresholds, 340 pairs.

| | rate |
|---|---|
| CONTRADICT pairs the gate verified | 19/71 = **26.8%** [17.8, 38.0] |
| NEI pairs the gate verified | 30/131 = 22.9% [16.5, 30.8] |
| SUPPORT pairs the gate refused | 43/138 = 31.2% [24.0, 39.3] |
| precision of "verified" on this label mix | 95/144 = 66.0% [57.9, 73.2] |

This is the uncomfortable result and it is the reason the benchmark exists.
Quote-match still guarantees the cited span is real; the NLI layer
(DeBERTa-v3-base, MNLI/FEVER/ANLI-trained, out-of-domain here) is what lets a
contradicted claim through: of 49 dev false accepts, 24 were scored
*entailment* — no threshold can catch those. Thresholds only trade the two
errors (train-chosen points, evaluated once on dev):

| operating point | CONTRADICT verified | NEI verified | SUPPORT refused | precision |
|---|---|---|---|---|
| shipped (contr >= .40, neutral >= .85, no entailment floor) | 26.8% | 22.9% | 31.2% | 66.0% |
| entailment >= .3, neutral >= .7 | 15.5% | 14.5% | 37.7% | 74.1% |
| entailment >= .5, neutral >= .5 | 12.7% | 10.7% | 41.3% | 77.9% |
| entailment >= .6, neutral >= .5 | 9.9% | 7.6% | 47.1% | 81.1% |

What this does and does not say: SciFact claims are expert-written and its
CONTRADICT claims are deliberate negations, which is harder than a drafting
model paraphrasing the very span it quotes. So production false-accept is
probably LOWER than 24% — but that is unmeasured, and "probably" is not a
number. Until a stronger verifier moves the held-out figures (launch blocker
L10), "verified" means *quote-matched and entailment-checked*, not *proven*.
Re-run against a candidate with `--nli-model`.

### Not measured yet (do not claim)

- **Extraction accuracy** — are the numbers and their context (metric, dataset,
  baseline) right? Needs human-extracted gold on real papers; the harness shape
  is `extraction_ab.py` + `evidence_bench.py`, the gold does not exist yet.
- **Conclusion agreement** with published reviews (e.g. MedEvidence, 284
  questions from 100 Cochrane reviews). D sentences state counts, not
  conclusions, so this needs the I-sentence design first.
- **End-to-end replication** of the Hall review through search, ingest and
  extraction (the screen is measured; the rest of the funnel is not).
- **Researcher time saved.** Needs a task-based study with real researchers.

## Online metrics & tracing

- **Prometheus** (`/metrics`) + alert rules (`deploy/observability/alerts.yml`):
  per-node latency, LLM calls/tokens, gate verified-fraction, ingest health.
- **Per-project dashboard** (`GET /api/projects/:id/dashboard`): verification
  health, cost/tokens, latency, retrieval quality, corpus, provider health, runs.
- **LLM tracing — pick ONE:**
  - **LangSmith** (recommended, LangGraph-native): set `LANGSMITH_API_KEY`
    (+ `[langsmith]` extra). `init_langsmith()` wires `LANGCHAIN_*` at startup so
    the LangGraph pipeline emits its node-level run tree automatically; our raw
    LLM calls are posted as LangSmith runs tagged with the run_id, so generations
    correlate with the node tree. Its dataset+eval workflow is the natural home
    for growing the golden sets.
  - **Langfuse** (self-hostable): set `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`.

  Both are optional and fully defensive (missing package / SDK error = silent
  no-op). Running both just double-reports — choose one.

## The rule that keeps trust honest

An LLM judge (RAGAS, LangSmith evaluators) may **annotate** quality, but it never
**gates** truth. Truth is decided only by the deterministic gate (verbatim
quote-match + NLI entailment). This is the invariant that separates "verified"
from "a model thought it looked right."
