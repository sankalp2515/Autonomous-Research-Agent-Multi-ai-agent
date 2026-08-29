`app/agents/synthesis.py` is deterministic. **No LLM runs in it at all.** It turns the
evidence matrix into a statement about what the *body* of evidence supports, and it is
computed at the end of `extract_evidence` so the architect can structure the report around
what is settled and what is disputed.

## Comparability is computed, never assumed

`app/agents/normalize.py` parses each finding's value into a number and a unit, and pairs
it with the context the paper actually stated: dataset, task, baseline, model, condition.

Two numbers are the same measurement only if **dimension, metric, dataset, task and unit
all match**.

:::danger The failure no grounding gate can catch
Two studies both reporting 89.2 are not corroboration when one is F1 on HotpotQA and the
other Recall@10 on MuSiQue. Each number is real. Each quote is verbatim. Each claim passes
the gate. The fabrication would happen in the **aggregation** — which is why aggregation
gets its own rules rather than being left to a language model's sense of similarity.
:::

### Unknown context never counts as matching

A missing dataset field means *we do not know*, not *the studies agree*. Unqualified
numbers stay out of every comparable bucket rather than being pooled into a default one.

This costs fill rate and it is the correct trade. A pooled average over incomparable
conditions is a number with no referent.

## A disagreement is not a dispute until conditions are checked

Two comparable numbers differing by more than **10%** — and more than **2 percentage
points** on percentage axes — are a **contradiction candidate**. Then:

| Situation | Reported as |
| --- | --- |
| The studies recorded different baseline, model or condition | *explained by conditions* |
| No stated difference accounts for it | a genuine tension |

Only fields **both** studies stated are compared. Explaining away a real disagreement is
the more damaging of the two possible errors, so the system errs toward calling it a
tension rather than inventing a reconciliation.

## Evidence strength is a study count

There is deliberately **no 0–1 confidence number**.

| Class | Requires |
| --- | --- |
| `strongly_supported` | ≥5 independent studies **and** ≥3 measuring it the same way |
| `moderately_supported` | Breadth without comparability tops out here |
| weaker classes | Fewer studies, or no comparable measurement |

Every class carries a `basis` string naming the counts that produced it. A reader can
audit the classification instead of trusting a score whose derivation is invisible.

Breadth without comparability cannot reach the top class. Five studies that each measured
something different are five interesting facts, not one strong finding.

## NLI is not evidence strength

`synthesis.py` reads no NLI value anywhere, and the persisted JSON carries a `note` saying
so — because this is the most likely misreading of the system.

The gate's entailment score says a sentence is faithful to its source. It says nothing
about how many independent studies found the effect. Two entirely separate questions, two
entirely separate mechanisms.

This is also distinct from `app/services/analysis.py`, which runs NLI over claim **pairs**
to answer "do these two sentences conflict?" — a question about language, not about
evidence. Both ship, and they are not interchangeable.

## Gaps are counted, never generic

`research_gaps()` derives four kinds from study counts:

| Kind | Definition |
| --- | --- |
| `under_measured` | One axis sits at ≥60% coverage while this one is at ≤34%. |
| `single_study` | Exactly one study measured it. |
| `no_comparable_evidence` | ≥3 studies measured it, but no two measured it the same way. |
| `contested` | Comparable measurements genuinely disagree. |

Every gap carries a `basis` naming its counts. `tests/test_gaps_and_genre.py` asserts that
every `basis` contains a digit — a mechanical guard against the sentence this module
exists to never print, which is *"more research is needed"*.

`no_comparable_evidence` deserves particular attention: it is the gap a fill-rate metric
hides completely. The matrix looks full. The column is populated. And nothing in it can be
compared to anything else in it.

## Study characteristics

Before any claim drawn from the sample, the dossier describes the sample: year span,
systems, benchmarks, baselines, backbone models, full-text share, and **framework
concentration**. If one system dominates the corpus, every conclusion is really about that
system — and the reader should be told before, not after.

## Related

- [Cell states](#/docs/explanation/cell-states)
- [Compare papers](#/docs/features/compare)
