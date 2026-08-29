The Map is a similarity graph over the papers in your corpus. Each paper is a
node; an edge means two papers are semantically close. Clusters are sub-communities
of related work, and the gaps between them are usually the interesting part.

## What it does

Every paper is embedded as `title + opening chunk`. Each node draws edges to its
**4 nearest neighbours** (`NEIGHBORS = 4`) where cosine similarity is at least
**0.55** (`SIM_THRESHOLD`). A union-find pass over those edges assigns each node a
**cluster id** — that is what the colours mean. A deterministic
Fruchterman–Reingold force layout then positions everything.

:::note Why the layout is computed on the server
Positions are precomputed server-side and cached in Redis for 30 minutes, so the
browser never re-runs an O(n²) force simulation on mount. The map opens instantly
and the frontend only reads `x`/`y`. The layout is seeded on a circle
deterministically, so **the same corpus always produces the same map** — you can
recognise your own field's shape between sessions.
:::

Local embeddings only. No extra API calls, no external service.

## How to use it

**Read the shape first.** Before clicking anything, look at the structure:

| What you see | What it usually means |
| --- | --- |
| A dense cluster | A well-covered sub-area. Your corpus is deep here. |
| A node bridging two clusters | A paper connecting two lines of work — often the most useful thing in the corpus. |
| An isolated node | Either genuinely novel, or off-topic and worth removing. |
| One giant cluster, nothing else | Your corpus is narrower than you think. Widen the search. |

**Select a node** to highlight its closely-related papers and open its panel. From
there:

- **Add to compare** — start building a comparison set.
- **Add neighbours** — pull that node's highlighted neighbours into the set in one
  click. This is the fastest path from "this paper matters" to a grounded
  side-by-side.
- **Ask this paper** — opens a drawer for scoped chat against that document alone
  (`document_id` on `/api/chat`), so retrieval never leaves that paper.
- **Add to chat** — puts the paper into the app-wide
  [chat context](#/docs/features/chat-context) instead, so you can gather items
  across views first.

**Send two or more picks to Compare.** The compare tray appears once you have at
least two selected.

**Refresh** when you have ingested new papers:

```bash
curl "http://localhost:8210/api/projects/<project_id>/map?refresh=true"
```

Without `refresh=true` you get the cached map for up to 30 minutes.

## What it gives you

- **Orientation you cannot get from a list.** A documents table sorted by date
  tells you nothing about structure. The map shows which papers belong together
  before you have read them.
- **A shortcut into Compare.** Neighbours in the graph are the papers most likely
  to be worth comparing, and there is a one-click path.
- **A corpus quality check.** If the map is one blob, your sourcing was too
  narrow. If it is confetti with no edges, your corpus is incoherent and the
  report will read that way.
- **Real relationships, from your data.** Edges come from the content of papers
  you actually ingested — not from a citation API's idea of relatedness.

## Limits worth knowing

- **Papers only.** Nodes come from indexed documents of type `paper` and `upload`.
- **Similarity is not citation.** An edge means "these read alike", not "one cites
  the other". Citation edges are a separate, off-by-default feature
  (`MAP_CITATION_EDGES_ENABLED`).
- **The embedding is title plus opening chunk**, not the whole paper. That is
  usually the abstract, which is the right signal for topical similarity and the
  wrong signal for methodological similarity.
- **Thresholds are constants** in `app/services/mapping.py`, not settings.
- **The view is code-split** — it loads on demand, because the force layout and
  SVG are heavy and most sessions never open it.

## Related

- [Compare papers](#/docs/features/compare)
- [The + Chat button](#/docs/features/chat-context)
- [Bring your own papers](#/docs/how-to/bring-your-own-papers)
