The small **＋ Chat** pill that sits next to papers, claims and answers builds a
one-off conversation scope. Pick items from anywhere in the app, then ask a
question grounded in **exactly that set**.

## Where the button appears

It is deliberately everywhere an entity is rendered, so "ask about this" is never
more than one click away.

| Surface | What you are adding | Kind |
| --- | --- | --- |
| **Documents** list | A paper | `document` |
| **Map** node panel | A paper | `document` |
| **Report** — beside any claim, sub-theme row or table cell | A verified claim | `claim` |
| **Ask** — beside any answer | A past answer, with its claims | `answer` |

The pill toggles. Unselected it reads **＋ Add to chat**; selected it turns
accent-coloured and reads **✓ In chat**. On dense surfaces such as claim rows it
renders as a compact icon-only pill.

## The tray

As soon as one item is selected, a floating tray appears — and it follows you
across views, which is the whole point. You can pick two papers in Documents, a
claim in a report and an answer from Ask, and they all land in the same set.

The tray shows a count, a summary (*"2 papers · 1 claim selected for chat"*), a
removable chip per item, **Clear**, and **Chat with selection →**.

## What happens when you ask

Your selected `entity_refs` are resolved into two things:

1. **A document scope** — the set of documents those items belong to. Retrieval is
   restricted to it (`top_k=16`, at most 3 chunks per document).
2. **Seed chunks** — the exact passages behind the claims and answers you picked.

The seeds are placed **first** in the drafting context and guaranteed to be there;
retrieved chunks follow, deduplicated by `chunk_id`. So the specific evidence you
selected is never crowded out by whatever retrieval happened to rank highly.

The answer then goes through the full gate. An ad-hoc context is verified exactly
like everything else — selecting your own evidence does not lower the bar.

If none of your selections resolve to sources in this project, you get a refusal
saying so rather than a silent fallback to the whole corpus.

## What it is good for

| Situation | Why the selection helps |
| --- | --- |
| Three papers seem to disagree | Scope the question to just those three and ask where they diverge. |
| A claim looks surprising | Add it, add the paper, ask what conditions it held under. |
| You are drafting a section | Gather the six claims you intend to use and ask what they collectively support. |
| A map cluster looks coherent | Add the cluster's papers and ask what they share. |

The common thread: **precision beats recall** here. Corpus-wide Ask is a wide net;
selection chat is a scalpel for a question you have already narrowed.

## Limits worth knowing

- **Up to 50 refs** per request.
- **The selection is session state.** It lives in React state, not the database —
  a reload clears it. It is a scratchpad, not a saved set. If you want the set to
  persist, make it a [comparison](#/docs/features/compare) or save the claims to
  the [notebook](#/docs/features/notebook).
- **Selection chats do not join your main history.** They are persisted with
  `kind = "selection"` and excluded when corpus chat history is restored.
- **The scope is documents, not chunks.** Adding one claim brings its whole
  document into retrieval range, plus its own chunk as a guaranteed seed. That is
  usually what you want — a claim without its surrounding paper is hard to
  interrogate.

## Related

- [Ask the corpus](#/docs/features/ask) — the three chat modes.
- [Compare papers](#/docs/features/compare) — when the selection deserves to be permanent.
- [Notebook](#/docs/features/notebook)
