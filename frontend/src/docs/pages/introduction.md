Veriscope is a research workspace that is **verifiable by construction**. A multi-agent
pipeline searches arXiv and Semantic Scholar, ingests the papers it finds into a
per-project corpus, and drafts a report in which **every sentence you read has already
survived a verification gate** — or it is not shown at all.

Most AI research tools fabricate. Plausible summaries, citations that are subtly wrong,
sources that do not exist, numbers no paper reported. You end up re-verifying everything
by hand and the time saving evaporates. Veriscope inverts the default: nothing reaches
the reader unless it passes.

:::note The one-paragraph version
A claim must (1) cite a real chunk that exists in your corpus, (2) carry a verbatim quote
that exact-matches that chunk character-for-character, and (3) be entailed by that chunk
under a local NLI model. Failing claims are regenerated, dropped, or surfaced as an
honest gap. References render only from resolved citation rows — so a fabricated citation
has no row and *cannot* render.
:::

## What you can do with it

| Capability | What it is |
| --- | --- |
| **Deep research run** | A question goes in; a structured, fully-cited report comes out, with an evidence matrix of every study read. |
| **Grounded chat** | Q&A over everything the project has ever ingested, with click-to-source provenance and refusal when evidence is absent. |
| **Evidence matrix** | One row per study, one column per comparison dimension. Every cell is a gate-verified claim. |
| **Live run feed** | A truthful instrument: typed progress events, a server-computed clock, and refusals shown as refusals. |
| **Compare, monitor, map** | Diff two reports, watch the literature for new work, and see how sources relate. |

## How this documentation is organised

These docs follow the [Diátaxis](https://diataxis.fr) framework. Four kinds of
documentation answer four different questions, and mixing them is what makes most
technical docs frustrating to read.

| Section | Answers | Read it when |
| --- | --- | --- |
| **Tutorials** | "Can you walk me through it?" | You are new and want to learn by doing. |
| **How-to guides** | "How do I accomplish X?" | You have a specific goal in mind. |
| **Reference** | "What exactly does this do?" | You need precise, lookup-style facts. |
| **Explanation** | "Why is it built this way?" | You want the reasoning and the trade-offs. |

Alongside those four there is a **Features** section: one page per surface —
[Ask](#/docs/features/ask), [Screening](#/docs/features/screening),
[Compare](#/docs/features/compare), [Map](#/docs/features/map),
[Monitor](#/docs/features/monitor), [Notebook](#/docs/features/notebook),
[Notes](#/docs/features/notes), [Memory](#/docs/features/memory) and
[the + Chat button](#/docs/features/chat-context). Each answers the same four
questions in the same order: what it does, how to use it, what it gives you, and
where its limits are.

If you are new, start with [Install and run](#/docs/start/install), then the
[first verified report](#/docs/tutorials/first-report) tutorial. If you are evaluating
the system's trustworthiness, go straight to
[The grounding contract](#/docs/explanation/grounding-contract).

## The shape of the system

```diagram:system
```

## The guarantees, stated plainly

These five are non-negotiable. Every change to the codebase is measured against them,
and there are tests pinning each one.

| # | Guarantee | Enforced by |
| --- | --- | --- |
| **G1** | Every claim traces to a source span — one `chunk_id` plus a verbatim quote. | Claim objects carry evidence end to end; no span, no claim. |
| **G2** | Zero fabricated citations. | References render only from resolved `Citation` rows; the report renders only from gate-verified `Claim` rows. |
| **G3** | Closed corpus by default. | Retrieval is project-scoped at the store level. |
| **G4** | Refusal over fabrication. | "Your corpus doesn't cover this" is a first-class, well-designed state. |
| **G5** | Honest gaps. | Unsupported sections are labelled, never papered over. |

:::warn Density comes from evidence, not from prose
There is no free-form connective text between verified claims. Reorganising verified
claims into tables and sub-themes is allowed; authoring new sentences is not. This is why
a Veriscope report reads dense — there are simply *more verified claims*, not more filler.
:::

## Where to go next

- [Install and run](#/docs/start/install) — get it running locally or in Docker.
- [Architecture overview](#/docs/start/architecture) — the map before the territory.
- [Your first verified report](#/docs/tutorials/first-report) — end to end, in one sitting.
- [API reference](#/docs/reference/api) — every endpoint.
