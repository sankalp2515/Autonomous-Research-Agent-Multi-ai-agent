By the end of this tutorial you will have produced a report in which you can click any
sentence and land on the exact sentence of the exact paper it came from — and you will
know how to tell a genuine evidence gap from a limitation of the tool.

:::note What you need
A running Veriscope (see [Install and run](#/docs/start/install)) and about 40 minutes of
wall-clock, most of which the machine spends downloading and parsing PDFs. You do not
need to sit and watch it.
:::

## 1. Create a project

A project is the unit of corpus isolation. Everything a run ingests lands in the
project's corpus and stays there, so a second question on the same topic starts from the
papers the first one already read rather than from nothing.

From the home screen, choose **New project**, give it a name that describes the *area*
rather than the question — "Retrieval-augmented generation" rather than "Is RAG better
than fine-tuning" — and open it.

## 2. Ask a question the system can actually answer

The `clarify` node runs an intent guard first. It rejects asks that are not research
questions, then decomposes what remains into two to five answerable sub-questions.

Good questions have a shape:

| Shape | Example | Genre the architect will design for |
| --- | --- | --- |
| Comparison | "How do dense and sparse retrievers compare on multi-hop QA?" | comparison |
| Decision | "Should we fine-tune or use RAG for a domain assistant?" | decision |
| Evolution | "How have long-context attention methods changed since 2023?" | evolution |
| Mechanism | "Why does chain-of-thought improve arithmetic reasoning?" | mechanism |
| Evaluation | "How is factual consistency in summarisation measured?" | evaluation |

Type your question and start the run.

## 3. Watch the run honestly

The research screen is the surface where you decide whether to trust the machine, so it
is held to the same standard as the report itself.

- **The clock is computed server-side.** It ticks while the pipeline is inside a long
  node. A frozen clock would mean something is genuinely wrong.
- **Every event is typed at the publish site** — `stage`, `search`, `ingest`, `corpus`,
  `extract`, `recover`, `verify`, `refuse`, `error`, `done`. The feed colours and groups
  on that type, never by pattern-matching the message text.
- **The feed keeps the whole run.** Scroll back. The two most informative things that
  happen are a **refused claim** and a **paper with no accessible full text** — both are
  marked, neither scrolls past silently.

The stepper names the real graph nodes. When it reaches `extract_evidence` the system is
reading each paper on its own terms, which is the slowest and most valuable stage.

:::tip Nothing is lost if you close the tab
Every node checkpoints. Come back later and the run either finished or can be resumed
from the last checkpoint.
:::

## 4. Read the evidence before anyone's synthesis of it

The finished report opens with the **evidence matrix** — one row per study, columns being
the comparison dimensions ordered by how many studies report each. It is rendered *before*
the prose deliberately: you meet the studies before you meet a synthesis of them.

Every cell is one of four states, and the difference matters more than anything else on
the page:

```diagram:cell-states
```

| Cell | Read it as |
| --- | --- |
| a finding | This study reported this. |
| `not reported` | This study does not report it — **and we searched properly**. |
| `not applicable` | The axis cannot apply to this study. |
| `extraction uncertain` | **We** could not establish either way. A fact about Veriscope, not about the literature. |

The fourth state exists because the honest alternative — printing an em-dash and calling
it "the study did not report that" — was false for roughly 30 of 62 empty cells on the
calibration run. The paper reported the number; retrieval never reached the page.

## 5. Follow one claim all the way down

Click any superscript citation in the prose. The **evidence rail** pins beside your
reading column, and it does not cover the text:

1. the sentence, as the report states it;
2. the verdict — quote-match plus the NLI entailment score;
3. the **verbatim span**, highlighted character-for-character inside;
4. the source passage it was taken from;
5. the document, with its page range and resolver badge (arXiv, DOI or corpus).

That chain is the product. The stamps say the checks passed; the chain says what was
checked.

:::warn What the NLI score is not
It says the sentence is *faithful to its source*. It says nothing about how many
independent studies found the effect. Evidence strength is a study count and is computed
separately — see [Counting studies, not sentences](#/docs/explanation/synthesis).
:::

## 6. Check what the report is not telling you

Open the **dossier** — the four-face panel folding Sample, Evidence, Gaps and Methods.

- **Sample** describes the corpus before any conclusion drawn from it: year span, systems,
  benchmarks, baselines, backbone models, full-text share, and framework concentration.
  If one system dominates, every conclusion is really about that system.
- **Gaps** are counted, never generic. Each one carries a `basis` naming the numbers that
  produced it — `under_measured`, `single_study`, `no_comparable_evidence`, `contested`.
  "More research is needed" is the sentence this panel exists to never print.
- **Methods** is the funnel: found → screened → ingested → extracted → cited, plus what was
  refused at each step.

Note the gauge reads **"Sections grounded"**, not "Coverage". It says every section found
evidence it could verify — a fact about the report, not about the field.

## What you learned

- A project is a persistent corpus, not a scratchpad.
- Question shape determines report genre, which determines structure.
- Four cell states, one of which is about the tool rather than the literature.
- Every sentence has an address, and the rail is how you visit it.

## Next

- [Ask questions about your corpus](#/docs/tutorials/grounded-chat) — the chat surface.
- [Run a deep research run](#/docs/how-to/run-deep-research) — the same thing, as a
  reference procedure with all the knobs.
- [The grounding contract](#/docs/explanation/grounding-contract) — why any of this holds.
