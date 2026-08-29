Veriscope exists because of a specific empirical finding. Around 55 real complaints about
AI research tools — SciSpace, Elicit, Consensus, NotebookLM, ChatGPT — were analysed from
Reddit, Capterra and academic forums. The dominant failure was not retrieval quality. It
was **trust**.

> Sources that didn't exist at all. Fabricated references. Exact figures not supported by
> the original paper.

The pattern is always the same: plausible at first glance, wrong on verification. So users
re-read every source anyway, and the time saving evaporates.

**Research is a trust problem, not a retrieval problem.** Every architectural decision in
this system follows from taking that seriously.

## The five guarantees

| # | Guarantee | What it rules out |
| --- | --- | --- |
| **G1** | Every claim traces to a source span — one `chunk_id` plus a verbatim quote. | A sentence with no address. |
| **G2** | Zero fabricated citations. | A reference to a paper that does not exist. |
| **G3** | Closed corpus by default. | Model-memory leaking in as if it were a source. |
| **G4** | Refusal over fabrication. | A confident answer where there is no evidence. |
| **G5** | Honest gaps. | Silence about what could not be verified. |

## Why these are structural, not procedural

The important word in G2 is *structurally*. Consider how a fabricated citation would have
to happen:

1. The UI renders references **only** from resolved `Citation` rows.
2. A `Citation` row is written only after resolution against CrossRef, OpenAlex, arXiv or
   the corpus itself.
3. Therefore a made-up citation has no row.
4. Therefore it cannot render.

There is no step where a model is trusted not to invent one. The LLM never authors a `[N]`
marker anywhere in the system — numbering is generated at render time from claim-to-chunk
links. A guarantee that depends on a model behaving well is not a guarantee.

## The design laws underneath

**1. Agents propose, deterministic verifiers dispose.** LLMs never have final authority
over what the reader sees.

**2. Verification gates; it never merely observes.** This is the fatal flaw the current
architecture was built to correct. The first version computed a grounding score and an
`unsupported_claims[]` list *after* generating the report — and then shipped anyway. A
number on a dashboard is not a gate. Failing claims are now stripped, regenerated or
surfaced as explicit gaps, and that is enforced by **graph topology**, not by convention.

**3. Loops, not a one-shot DAG.** `plan` is revisitable. Drafting has a conditional edge
back to it for the failing sub-question only, with hard budget caps.

**4. Citations are structured objects end to end.**

**5. Synthesis reads chunks, not prior LLM prose.** No triple compression from chunks to a
RAG answer to a synthesis. Each synthesis unit receives raw chunk text and span IDs.

**6. Evals before features.** Per-stage metrics, so "the results are bad" becomes
debuggable.

## Density is achieved by grounded means

The report reads like a premium, high-density research analysis. That density comes from
**more verified claims plus structural richness** — never from ungrounded connective
prose.

There is no free-form LLM-written sentence between verified claims. Reorganising verified
claims into tables and sub-themes is allowed; authoring new sentences is not. Every
sentence a reader sees passed the gate.

This constraint is unusual and it is the whole point. The moment one paragraph of
smoothing prose is allowed "just to connect two claims", the reader can no longer assume
that what they are reading was checked — and the value of everything else on the page
drops with it.

## What the contract does not promise

- **It does not promise the papers are right.** A verified claim faithfully reports what a
  source said. Sources are wrong sometimes.
- **It does not promise completeness.** The [funnel](#/docs/explanation/funnel) exists to
  say exactly how far the review reaches.
- **It does not promise the synthesis is the only reading.** Comparability and
  contradiction are computed with stated rules — see
  [Counting studies](#/docs/explanation/synthesis).

Being explicit about the boundary is part of the contract. A guarantee that quietly
overclaims is the failure mode this system exists to avoid.

## Related

- [The verification gate](#/docs/explanation/verification-gate) — the mechanism.
- [Cell states](#/docs/explanation/cell-states) — the contract applied to absence.
