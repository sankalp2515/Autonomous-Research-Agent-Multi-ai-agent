# Verification-gate threshold calibration (audit A3)

The gate ships four tunable thresholds. Before this doc they were seeded by
judgement and never measured. This records **what they are, how to re-measure
them, and the current evidence**.

## Thresholds

| Setting | Default | Role |
|---|---|---|
| `nli_contradiction_threshold` | 0.40 | contradiction at/above this confidence → reject the claim |
| `nli_neutral_reject_threshold` | 0.85 | strong-neutral (chunk says nothing about the claim) → reject as out-of-context. **Promoted from a hardcoded `0.85` literal** so it is calibratable. |
| `quote_fuzzy_threshold` | 0.92 | normalized-fuzzy quote match below this → quote fails. Means a "verbatim" quote may drift up to ~8% of characters (PDF noise tolerance). |
| `nli_entailment_threshold` | 0.60 | **RESERVED / NOT ENFORCED.** The gate rejects contradictions and strong-neutrals but does **not** currently require a minimum positive entailment score. `calibrate.py` reports what enforcing it would change. |

## How to run

Needs the local ML stack; needs no DB/Redis/Qdrant.

```bash
cd backend
pip install -e ".[ml]"
ML_NLI_ENABLED=true python -m evals.calibrate
```

It reports the confusion matrix at the shipped thresholds (false-**accepts**
first — a false accept is a silently-wrong "verified" result), a per-category
breakdown, a sweep over each threshold, and the entailment-enforcement what-if.
Exit code is 0 only when there are **zero false-accepts**.

## Current evidence (labeled boundary set, `evals/calibration_set.json`, 12 cases)

At the shipped thresholds:

- **false-accepts: 0** — no unsupported claim verified.
- **false-rejects: 0** — no supported claim was refused.
- Every category correct (clear entailment, numeric/polarity contradiction,
  out-of-context neutral, scope over-reach, fabricated quote, over-specified
  entity, fuzzy PDF-noise quote, weak entailment).
- **Robust to the sweep:** FA=FR=0 held for contradiction ∈ {0.30–0.60},
  strong-neutral ∈ {0.70–0.90}, quote-fuzzy ∈ {0.88–0.98}. The decision is not
  balanced on a knife-edge on this set.
- **Enforcing `nli_entailment_threshold ≥ 0.60` would catch 0 additional
  false-accepts and add 0 false-rejects** — on this set it closes no leak, so it
  stays reserved rather than wired (wiring it would add false-reject risk for no
  measured gain).

## Honest caveat / decision

12 cases is a **boundary probe**, not a statistically powered benchmark. The
result says "no leak is visible at the decision boundaries we could construct,"
**not** "calibrated to a confidence interval." Two follow-ups remain open
(tracked as A2/A3 in `backend/PRODUCTION_TODO.md`):

1. Grow the labeled set (target 50–100 cases, adversarial + real-corpus) so the
   false-accept rate has a meaningful denominator.
2. Re-run `calibrate.py` on that set and only then treat the thresholds as
   data-backed. Wire it into CI as a soft gate once trusted.

The 0.92 fuzzy-quote bar is a **deliberate** trade (PDF text is noisy); the
sweep shows tightening it to 0.98 costs no correctness on this set, so it can be
raised if a future corpus shows quote-drift false-accepts.
