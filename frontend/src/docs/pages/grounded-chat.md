A deep research run answers one big question. Grounded chat answers the hundred small
ones that follow it — over everything the project has ever ingested, with the same
provenance guarantees and the same willingness to refuse.

:::note What you need
A project with at least one completed run, or a handful of PDFs you have uploaded. Chat
retrieves from the project corpus; an empty corpus can only produce a refusal.
:::

## 1. Ask something the corpus can answer

Open **Chat** inside a project and ask a specific question — "which of these papers
evaluated on HotpotQA, and what did they report?" rather than "summarise this field".

Behind the scenes the request runs hybrid retrieval over the project's chunks (BM25 and
dense vectors fused, then reranked), builds a synthesis unit from the raw chunk text, and
sends every resulting sentence through the same gate the report drafting uses.

## 2. Read the answer as a set of claims

What comes back is not a paragraph. It is a list of claims, each carrying its own citation
and its own evidence. Click one and the evidence drawer shows the quote and the passage,
exactly as the report's rail does.

If a sentence could not be grounded, it is not in the answer. There is no "here is my
best guess" mode.

## 3. Now ask something the corpus cannot answer

Ask about a topic you know is not in your project — a different field entirely.

You will get a **refusal**: a clear statement that the corpus does not cover this, and
what is missing. This is the behaviour that makes the other answers worth trusting. A
system that always produces something teaches you nothing about when to believe it.

:::tip Refusal is a signal, not a failure
A refusal usually means one of three things: the corpus genuinely lacks the material,
your question is outside the project's area, or the phrasing missed the corpus vocabulary.
Try the third first — rephrase using the terms the papers themselves use.
:::

## 4. Turn a good answer into something durable

Three things you can do with an answer worth keeping:

| Action | What it does |
| --- | --- |
| **Save to notebook** | Pins the answer and its evidence in the project notebook. |
| **Add a note** | Your own commentary, stored alongside the corpus. |
| **Refind** | Re-runs the retrieval for a claim so you can see what else supports it. |

## 5. Understand what chat will not draw on

Scholarly evidence (papers and your uploads) and practitioner evidence (repos and blogs)
never share a drafting context. Chat claims are drawn **only** from scholarly evidence.
Practitioner hits are attached separately as technical context, clearly labelled.

This is deliberate: a benchmark number from a peer-reviewed paper and a benchmark number
from a vendor blog post are not the same kind of fact, and blending them into one
paragraph destroys the reader's ability to weigh them.

## What you learned

- Chat is retrieval over the persistent project corpus, gated identically to reports.
- Answers are claims with addresses, not prose.
- Refusal is a designed state and is informative.
- Scholarly and practitioner evidence stay visually and structurally separate.

## Next

- [Ask the corpus](#/docs/features/ask) — the three chat scopes and how each is stored.
- [The + Chat button](#/docs/features/chat-context) — asking about an exact selection.
- [Bring your own papers](#/docs/how-to/bring-your-own-papers) — uploads and BibTeX import.
- [The grounding contract](#/docs/explanation/grounding-contract) — the rules behind all of it.
