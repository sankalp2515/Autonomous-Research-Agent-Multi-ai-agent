Veriscope ships evals because "the results are bad" is not a debuggable statement. Each
suite answers a different question, and the gate must pass before anything ships.

## The full verification sequence

```bash
cd backend
python -m py_compile app/agents/nodes.py app/agents/schemas.py app/api/routes.py
python -m pytest -q
python evals/run_evals.py
```

```bash
cd frontend
npx tsc -b && npx vite build
```

## The suites

| Command | Answers |
| --- | --- |
| `python evals/run_evals.py` | Does the overall gate still pass? Run this before every ship. |
| `python evals/retrieval_eval.py` | Is retrieval finding the right passages? |
| `python evals/run_report_evals.py` | Do generated reports meet the report-quality golden set? |
| `python evals/run_ragas.py` | RAGAS-style faithfulness and relevance metrics. |
| `python evals/calibrate.py` | Recalibrate gate thresholds against the calibration set. |
| `python evals/threshold_sensitivity.py` | How much does a threshold change actually move outcomes? |

Golden sets live beside them: `golden.json`, `report_golden.json`,
`calibration_set.json`.

## Evidence acquisition — never claim an improvement without these two

```bash
python -m evals.evidence_bench --report <report_id> --rerank
```

Measures **retrieval recall on cells whose evidence is genuinely in the corpus**. If a
cell is empty and the evidence was never there, that is not a retrieval failure and this
benchmark will not blame retrieval for it.

```bash
python -m evals.extraction_ab --report <report_id> --json new.json
python -m evals.extraction_ab --report <report_id> --legacy --json old.json
python -m evals.evidence_bench --report <report_id> --matrix new.json
```

A live A/B of the extraction layer over an **already-ingested** corpus, so the corpus is
held constant and only the extractor varies.

:::danger Fill rate is not the objective
`evidence_bench` reports `mislabeled_not_reported` alongside fill rate precisely so that
trading honesty for completeness shows up as a regression. A fabricated or contextless
value is worse than a correctly labelled hole. A change that raises fill rate and raises
mislabelling is a regression, not an improvement.
:::

## The test suite as a specification

Several tests exist specifically to pin decisions that were expensive to learn. Treat a
failure in these as a design regression, not a flaky test.

| Test | Pins |
| --- | --- |
| `test_screening_pools.py` | Ranking within source pools — the arXiv-erasure bug. |
| `test_evidence_schema.py` | The schema is derived, canonicalised and idempotent. |
| `test_dimension_retrieval.py` | Per-axis retrieval, including a fixture reproducing the original miss. |
| `test_evidence_matrix.py` | Matrix findings are real gated claims, not a second rendering path. |
| `test_completeness_recovery.py` | Every branch of the four cell states. |
| `test_synthesis.py` | Study counting, comparability, contradiction classification. |
| `test_evidence_normalization.py` | Value + unit parsing and context matching. |
| `test_gaps_and_genre.py` | Every gap `basis` contains a digit — no generic gaps. |
| `test_report_architect.py` | Report planning is separate from research planning. |
| `test_gate.py` / `test_quote_match.py` | The three gate layers. |
| `test_run_clock.py` | Server-computed elapsed time, both failure modes. |
| `test_run_lock.py` | Atomic job claim. |
| `test_research_funnel.py` | The ladder and `excluded_by_reason`. |
| `test_injection.py` | Prompt-injection resistance on ingested text. |

## Observability during a run

With Langfuse or LangSmith keys configured, every LLM call is traced with its node, its
prompt and its routing decision. OpenTelemetry export covers the API and worker spans.

## Related

- [Tune retrieval](#/docs/how-to/tune-retrieval)
- [Cell states](#/docs/explanation/cell-states)
