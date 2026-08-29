Memory is what the project carries between sessions. It closes the gap most
research assistants have — every run starting from nothing — so a second question
on a topic goes **deeper** instead of re-treading the first one.

## The rule that shapes everything else

:::danger Memory is never evidence
Memory is for **orientation and planning** — *"you researched X before"*. It is
deliberately kept out of the verification path. No claim may cite a memory, and
memory text never enters a drafting context as a source. The grounding invariant
is that claims cite verified source spans; a remembered summary is not one.
:::

Get this backwards and you have built exactly the failure mode this product
exists to prevent: a system confidently repeating something it "knows" with no
page to point at.

## What it stores

| Kind | Contents | Written by |
| --- | --- | --- |
| `episodic` | Summaries of past runs — what was researched and found | The pipeline's `build_graph` node |
| `semantic` | Durable facts about the project's subject area | You, or the pipeline |
| `preference` | How you want research done | You |

Each memory carries its text, a `source_ref`, optional metadata, and a timestamp.

## Where it is used

**At plan time.** The `plan` node consults project memory when composing search
queries, so a repeat question is informed by what the project already covered.
This is why the second run in a project is usually better than the first.

**On demand,** through recall — when you want to know what this project already
established.

## How recall works

Two-tier, with graceful degradation:

1. **Embedding recall** — your query and each memory are embedded locally; results
   are ranked by cosine similarity.
2. **Keyword + recency fallback** — if the ML stack is unavailable or a memory has
   no embedding, ranking falls back to overlap of query terms longer than three
   characters, preserving recency order.

Recall never fails hard. Without embeddings you get worse ordering, not an error.

## How to use it

**Browse** everything the project remembers, most recent first:

```bash
curl http://localhost:8210/api/projects/<project_id>/memory
```

**Recall** against a question (`q` at least 2 characters, `k` up to 20):

```bash
curl "http://localhost:8210/api/projects/<project_id>/memory/recall?q=multi-hop%20retrieval&k=5"
```

Each result carries its text, kind and score.

**Add one by hand.** Useful for standing preferences the agent should honour:

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/memory \
  -H 'Content-Type: application/json' \
  -d '{"kind": "preference", "text": "Prefer papers with released code and reproducible benchmarks."}'
```

`kind` must be one of `episodic`, `semantic`, `preference`; text is 3–2000
characters. Manual entries are recorded with `source_ref = "manual"`, so you can
always tell what the agent inferred from what you told it.

## What it gives you

- **Runs that compound.** Each question builds on the last rather than restarting.
- **Less duplicated searching.** The planner knows what ground is covered.
- **A record of the project's trajectory.** Browsing memory is the fastest way to
  reconstruct what you were doing three weeks ago.
- **Standing instructions that stick.** A preference written once applies to every
  later run in that project.

## Limits worth knowing

- **Project-scoped.** Memory does not cross projects. Two projects on adjacent
  topics learn nothing from each other.
- **No forgetting policy.** Memories accumulate. A stale preference stays
  influential until you remove it.
- **It influences planning, not verification.** A memory cannot make a bad claim
  pass, and cannot make a good one fail.
- **Recall quality tracks the embedding model.** Without the `[ml]` extra it is
  keyword matching.

## Related

- [Notes](#/docs/features/notes) — your writing, which never influences runs.
- [Pipeline nodes](#/docs/reference/pipeline-nodes) — where `plan` consumes memory.
- [The grounding contract](#/docs/explanation/grounding-contract)
