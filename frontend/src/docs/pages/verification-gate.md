The gate is deterministic, blocking and free-tier compatible. It runs on every claim the
system would otherwise show a reader — in reports, in chat, and in every cell of the
evidence matrix.

```diagram:gate
```

## Three layers, and why one is not enough

### 1. Citation resolution

The cited chunk must exist in the project corpus. This is cheap and catches the crudest
failure: a reference to something that was never retrieved.

### 2. Verbatim quote match

The claim carries a quote that must exist inside that chunk, character-for-character.
`QUOTE_FUZZY_THRESHOLD` (0.92) exists only to absorb PDF-extraction artefacts — ligatures,
hyphenation across line breaks — not to permit paraphrase.

### 3. NLI entailment

The claim must be **entailed** by the chunk under a local DeBERTa-class model. A
contradiction verdict always fails regardless of score. `NLI_ENTAILMENT_THRESHOLD` is
0.60; strongly-neutral verdicts are rejected at `NLI_NEUTRAL_REJECT_THRESHOLD` 0.85.

**Layer 2 alone** passes a real quote lifted out of context — the quote exists, but the
claim built around it does not follow from the passage. **Layer 3 alone** passes a
plausible paraphrase of a chunk that was never actually cited. Each layer closes what the
others leave open. That is why there are three, and why removing one is not a performance
optimisation.

## The reranker is not an entailment model

A cross-encoder scores **relevance**. Using it as a proxy for entailment was the specific
mistake the current architecture was built to correct. Relevance says a passage is
on-topic; entailment says the sentence follows from it. Only the second is a verification
signal, and conflating them produces a system that feels rigorous and is not.

## What happens to a failing claim

1. **Regenerate** with the gate's feedback, up to `SECTION_MAX_REGENS` (2).
2. **Bounded replan** — one edge back to `plan` for that sub-question, at most
   `SUBQUESTION_MAX_REPLANS` (1) times.
3. **Honest gap** — the section says what could not be verified.

At no point is a failing claim shown with a warning label. A hedge is not a gate.

## Fail-fast at boot

`assert_verification_ready()` refuses to start an environment that requires the NLI truth
layer but has it switched off:

> `ML_NLI_ENABLED=false` is not permitted when `APP_ENV=prod` — the gate would ship claims
> on quote-match alone, silently dropping the out-of-context check.

Both entry points (API and worker) call it, so a misconfigured deployment dies loudly at
boot rather than shipping quote-only "verified" claims at run time. The gate itself is the
hard backstop; this is the friendly early warning.

## NLI is not evidence strength

This is the most likely misreading of the whole system, so it is worth stating flatly.

The entailment score says **a sentence is faithful to its source**. It says nothing about
how many independent studies found the effect, how well-powered they were, or whether they
measured the same thing.

`synthesis.py` reads no NLI value anywhere, and the persisted JSON carries a `note` saying
so. Evidence strength is a **study count** — see
[Counting studies, not sentences](#/docs/explanation/synthesis).

In the UI, citation confidence colouring reflects gate strength (`--ok` for strong
entailment, `--warn` for quote-only or weaker). Evidence strength uses a different visual
language on purpose.

## The gate applies to recovered findings too

The recovery pass that re-reads papers for empty matrix cells does not get a discount. A
recovered finding is persisted as a real `Claim` plus `ClaimEvidence` and passes the same
gate. Recovery is not a back door around G1 and G2.

## Related

- [The grounding contract](#/docs/explanation/grounding-contract)
- [Cell states](#/docs/explanation/cell-states)
- [Evaluation](#/docs/reference/evals) — how thresholds are calibrated.
