The design system is called **Editorial Science**. Warm-paper surfaces, one scholarly
claret accent, hairline rules, calm long-reading. It is locked — not because it is
finished, but because a verification product cannot afford a visual language that shifts
underneath the reader.

## Why a research tool needs a strong visual identity

The product's core promise is that what you are reading was checked. That promise is
communicated almost entirely through visual grammar: what is set in the machine face, what
carries a score, what is separated from prose, what can be clicked to its source.

If those signals are inconsistent, the reader stops being able to tell verified content
from apparatus at a glance — and then they either trust everything or nothing.

## Type roles

| Face | Role |
| --- | --- |
| **Hanken Grotesk** | UI chrome — navigation, controls, labels. |
| **Spectral** (serif) | Report body and headings. The reading column. |
| **JetBrains Mono** | Provenance only — quotes, scores, ids. |

The mono face is the important one. **Anything machine-verified reads as
machine-verified.** A quote span, an NLI score and a `chunk_id` share a typeface because
they share a status: they are outputs of a deterministic check, not of a writer.

## Tokens

Defined once as CSS variables in `frontend/src/styles.css`. Use the tokens; never
hard-code a colour.

| Token | Value | Role |
| --- | --- | --- |
| `--bg` | `#f1f1ea` | Warm paper ground |
| `--surface` | `#fbfbf7` | Raised surfaces |
| `--ink` | `#1c1e17` | Warm near-black |
| `--accent` | `#8c2f39` | Scholarly claret — the single accent |
| `--ok` | `#356b4d` | Strong entailment |
| `--warn` | `#8a5a1a` | Quote-only or weaker |
| `--bad` | `#a3333a` | Failure, refusal |
| `--mark` | `#f6e9b8` | Verbatim quote highlight |

Because the app is fully token-driven, re-skinning is a token-and-font swap rather than a
rewrite.

Two semantic scales are kept apart on purpose: **citation authority** (counts) may use a
warm gold; **evidence strength** stays green and amber. Merging them would let a
well-cited paper look like a well-supported finding.

## The signature surface: the persistent evidence rail

Clicking any citation pins the exact quoted span, its NLI stamp and the source passage
**beside** the reading column.

Never a modal. A modal says *stop reading and look at this*; a rail says *here is the
proof, alongside the sentence it proves*. Verification that interrupts reading gets used
once and then avoided, and a verification feature nobody uses is decoration.

```diagram:report-anatomy
```

## Report structure

| Element | What it does |
| --- | --- |
| Analysis plan (`.rp-plan`) | The planning step, surfaced: objective, sub-questions, section mapping. |
| Sections and sub-themes | `##` numbered sections, `###` sub-themes from a structure call that reorganises verified claim indices and **never writes text**. |
| Comparison tables | Verified claims reorganised into a grid; every cell stays click-to-source. |
| Metric callouts (`.rp-metric`) | A claim carrying a concrete quantity **and** NLI ≥ 0.85, pulled out of the prose so it is never double-counted. |
| Inline footnotes | Small mono superscripts, coloured by gate confidence. |
| Works Cited (`.rp-cited`) | Numbered in citation order, each entry showing authors, year, resolver badge and the verbatim grounding span with page range and NLI score. |
| Evidence matrix (`.rp-matrix`) | Rendered **before** the prose — the reader meets the studies before anyone's synthesis of them. |
| Methods funnel (`.rp-methods`) | Corpus-level provenance, including what was refused. |

## The dossier

Sample, Evidence, Gaps and Methods fold into **one four-face panel**.

They used to stack into two screens of apparatus before the reader reached a finding. Do
not restack them. The audit trail is the product — but it is not the lede. A reader who
must scroll past the methodology to reach the result will stop reading the methodology
*and* the result.

## The provenance chain

`.ev-chain` is the traceability surface: sentence → verdict → character span → passage →
document. Each link is an address a reader can follow.

The stamps say the checks passed. The chain says **what was checked**. Those are different
claims, and a system that only shows stamps is asking for trust rather than earning it.

## The live run

The research screen is where a user decides whether to trust the machine, so it is held to
the report's standard:

- The clock is **computed server-side** against one reference `now`; the client ticks
  forward with a monotonic delta. Never re-derive elapsed time from a timestamp on the
  client.
- Every progress event is **typed at the publish site** with a `kind`. The feed groups,
  filters and colours on `kind` alone — never by pattern-matching our own prose, because
  rewording a message would then silently recolour a gate refusal as progress.
- The feed **keeps the whole run**. Consecutive duplicates collapse, auto-scroll unpins
  when the reader scrolls up, and the stepper names the real graph nodes.

## Motion and accessibility

Motion is 150–220 ms, ease-out, and `prefers-reduced-motion` is respected. Focus rings are
visible and token-coloured. Scholarly and practitioner evidence classes stay visually
separate; each source shows its year, and the report shows its true time span.

## Related

- [Architecture overview](#/docs/start/architecture)
- [The grounding contract](#/docs/explanation/grounding-contract)
