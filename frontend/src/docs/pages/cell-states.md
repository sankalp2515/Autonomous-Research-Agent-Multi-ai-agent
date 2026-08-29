The evidence matrix used to have two states: a finding, or an em-dash captioned *"this
study did not report that dimension"*.

On the calibration run, that caption was **false for roughly 30 of 62 empty cells**. The
paper reported the number; retrieval never reached the page. The report was publishing
*our* limitation as a fact about the literature — which is the single worst thing a
verification-first system can do. It is a fabrication that wears the costume of rigour.

```diagram:cell-states
```

## The four states

| State | Meaning | Who it is about |
| --- | --- | --- |
| `reported` | A gate-verified finding exists. | The study |
| `not_reported` | The study does not report it. | The study |
| `not_applicable` | The axis cannot apply to this study. | The study |
| `extraction_uncertain` | We could not establish either way. | **Veriscope** |

Three are claims about the literature. The fourth is a claim about the tool. Collapsing
them into one em-dash destroys exactly the distinction a reader needs.

## The rule that must never be relaxed

`not_reported` requires **evidence of search**:

- full text in hand — an abstract-only source can never qualify;
- at least `EVIDENCE_ABSENCE_MIN_QUERIES` (2) distinct queries against that axis;
- at least `EVIDENCE_ABSENCE_MIN_CHUNKS` (4) passages actually examined.

That is `coverage_is_sufficient()`. Everything else falls to `extraction_uncertain`:

- thin coverage;
- an abstract-only source;
- a gate failure on a recovered finding;
- a probe that returned no verdict;
- recovery disabled or budget-capped.

The asymmetry is deliberate. Claiming an absence is a strong assertion about a paper, and
strong assertions need the search to have happened.

## The recovery pass

After first-pass extraction, `_recover_unresolved` re-reads every paper that left a
required axis empty, with retrieval aimed at exactly those axes — batched to **one LLM
call per paper**, because per-cell would have cost roughly 60 calls per run.

Then `_attach_cells` records one of the four states for every study × required dimension
pair.

A recovered finding is persisted as a real `Claim` plus `ClaimEvidence` and passes the same
[gate](#/docs/explanation/verification-gate). Recovery buys better aim, not a lower bar.

## Fill rate is not the objective

This is the corollary anyone tuning the system needs to internalise.

`evals/evidence_bench.py` reports `mislabeled_not_reported` **alongside** fill rate,
precisely so that trading honesty for completeness shows up as a regression rather than as
progress. A change that fills 15 more cells and mislabels 4 absences has made the product
worse.

A fabricated or contextless value is worse than a correctly labelled hole. A reader can
work around a hole. They cannot work around a number they have no reason to doubt.

## Why this generalises

The same principle shapes several other surfaces:

- The report gauge reads **"Sections grounded"**, not "Coverage" — a fact about the
  report, not about the field.
- The [funnel](#/docs/explanation/funnel) is a ladder with named exclusions, never a single
  percentage.
- [Gaps](#/docs/explanation/synthesis) carry a `basis` naming the counts that produced
  them.

In each case the same question is being answered: *is this statement about the world, or
about us?* Systems that blur that line feel more confident and are less useful.

`tests/test_completeness_recovery.py` pins every branch above.

## Related

- [Tune retrieval](#/docs/how-to/tune-retrieval) — what to do when uncertainty is high.
- [The grounding contract](#/docs/explanation/grounding-contract)
