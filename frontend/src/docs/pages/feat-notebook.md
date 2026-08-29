The Notebook is where verified claims go when you want to keep them. It collects
findings **across every report and chat in the project**, and each one keeps its
exact quote and source.

## What it is — and what it is not

The Notebook holds **claims**, not your writing. Every entry is a `Claim` row that
already passed the verification gate; you are pinning a machine-checked finding,
not composing one. For your own words, use [Notes](#/docs/features/notes).

That distinction is deliberate. A notebook you can type into becomes a place where
unverified sentences sit next to verified ones and nothing tells them apart.

## How to use it

**Save.** Open any claim's evidence — click a citation in a report, an answer in
Ask, or a cell in a comparison — and hit *Save to notebook*. You can attach a short
note at the same time.

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/notebook \
  -H 'Content-Type: application/json' \
  -d '{"claim_id": "<claim-id>", "note": "the number we are going to quote"}'
```

Saving the same claim twice does not duplicate it — the second call updates the
note on the existing row and returns the same id.

**Review.** The Notebook view lists everything most-recent-first. Each entry shows
the claim text, its verbatim quote, and its source document and page.

**Export.** One click produces `findings_notebook.md`:

```text
1. Dense retrieval improves multi-hop recall by 12.4 points on HotpotQA.
   > "yields a 12.4-point absolute gain in Recall@10 over BM25"
   — Dense Passage Retrieval for Multi-Hop QA, p.6
   note: the number we are going to quote
```

Numbered claim, indented verbatim quote, source and page, and your note. It is
paste-ready into a draft with the provenance still attached.

**Remove.** `DELETE /api/notebook/{saved_id}` — this unpins the entry; the
underlying claim and its evidence are untouched.

## What it gives you

- **One place for the good bits.** Findings arrive scattered across reports, chats
  and comparisons. The Notebook is the project-wide collection point.
- **Quotes travel with claims.** When you paste an exported entry into a draft,
  the quote and page come with it, so the citation survives leaving the app.
- **A shortlist you can write from.** By the time you sit down to write, the
  Notebook is the set of things you decided were worth saying.
- **It survives the report.** A claim saved from a report you later supersede is
  still in the Notebook, with its source intact.

## Limits worth knowing

- **You can only save claims that exist.** There is no free-text entry.
- **It shows the first evidence row per claim.** A claim with multiple supporting
  chunks displays one quote — the primary one.
- **A deleted claim shows `(claim removed)`** rather than vanishing, so a gap in
  your notebook is visible rather than silent.
- **Export is client-side Markdown.** No PDF, no citation-manager format yet.
- **Notebook contents are not fed back into runs.** Saving something does not
  bias future research — that is [Memory](#/docs/features/memory)'s job, and the
  two are kept separate on purpose.

## Related

- [Notes](#/docs/features/notes) — for your own writing.
- [Memory](#/docs/features/memory) — for what the agent should remember.
- [Ask the corpus](#/docs/features/ask)
