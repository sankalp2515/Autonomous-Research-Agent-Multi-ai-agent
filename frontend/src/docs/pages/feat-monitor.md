A report is accurate as of the day it was assembled. The Monitor is the standing
agent that keeps the project honest about what has appeared since — it re-checks
your open questions against the literature and tells you when something new is
worth your attention.

## What it does

You keep a set of **watches** — standing queries. When a check runs, each active
watch is searched against live sources, results are compared against everything
the project already knows, the survivors are scored for relevance, and the good
ones land in your alert queue.

## Which sources does it search?

**Both arXiv and Semantic Scholar — every check, every watch.**

| Source | How it is queried |
| --- | --- |
| **arXiv** | `search_arxiv(query, max_results=12, sort_by="submittedDate")` — sorted by **submission date**, so it surfaces genuinely new preprints rather than the most-cited old ones. |
| **Semantic Scholar** | `search_semantic_scholar(query, max_results=12)` — default relevance ordering, covering published venues arXiv does not. |

Up to 24 raw candidates per watch, per check. The two result sets are pooled
before filtering.

:::note Why both, and why arXiv is sorted by date
Semantic Scholar has the published record and citation counts; arXiv has the
preprints, which in machine learning is where the work appears first. Sorting
arXiv by `submittedDate` rather than relevance is what makes the Monitor a
*monitor* — a relevance sort would keep returning the same seminal papers every
week.
:::

Note what it does **not** search: GitHub, blogs, or any practitioner source.
Those are a separate evidence class and are not part of monitoring.

## How a candidate becomes an alert

Four filters, in order. A candidate must survive all of them.

1. **Has an identity.** An `arxiv_id`, `doi`, `external_id`, or failing those the
   first 140 characters of its title. No identity, no alert.
2. **Not already alerted.** Checked against every `external_id` this project has
   ever been alerted about, so the same paper is never surfaced twice — including
   across separate checks and separate watches.
3. **Not already in the corpus.** Three-way dedup against your documents: known
   arXiv ids, known DOIs, and a fuzzy title match (`titles_match`) that catches
   the same paper arriving under a slightly different title.
4. **Semantically relevant.** The watch query and each candidate's
   `title + abstract[:400]` are embedded with the **local** embedding model, and
   cosine similarity must be **≥ 0.42**. The top **8 per watch** are kept.

```text
watch query
   ├── arXiv (12, newest first) ─┐
   └── Semantic Scholar (12) ────┴─→ identity? → not alerted? → not in corpus?
                                       → cosine ≥ 0.42 → top 8 → alert
```

If embedding is unavailable, every surviving candidate is scored a flat 0.5 and
kept — the Monitor degrades to dedup-only rather than failing.

**No LLM call is made anywhere in this path.** Search plus local embedding
scoring only, which is why a check is cheap enough to run often and works
entirely on free tiers.

## Where watches come from

You do not have to create any. The first time you open the Monitor,
`seed_watches` reads the project's most recent **completed** run and creates a
watch from each of its **sub-questions** (up to five). If the checkpoint has no
sub-questions, it falls back to the run's raw query.

So the Monitor starts watching exactly what you last researched — which is
almost always what you want it watching.

Seeding happens **only when the project has no watches at all**. Once you have
one, the Monitor never adds any behind your back.

## How to use it

**Add a watch.** Type a query (minimum 4 characters) and add it. Phrase it the
way the literature does, not the way you would ask a person — it is matched by
embedding similarity against titles and abstracts.

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/watches \
  -H 'Content-Type: application/json' \
  -d '{"query": "multi-hop retrieval evaluation"}'
```

**Pause a watch** instead of deleting it. Only `active` watches are checked.

```bash
curl -X POST http://localhost:8210/api/watches/<watch_id>/toggle
```

**Run a check.** Returns `202` immediately; the work happens in the background,
and the UI polls every 5 seconds for about 30 seconds.

```bash
curl -X POST http://localhost:8210/api/projects/<project_id>/monitor/check
```

**Act on an alert.**

| Action | Endpoint | Effect |
| --- | --- | --- |
| Add to corpus | `POST /api/alerts/{id}/add` | Ingests the paper — downloads, parses, chunks, embeds. |
| Dismiss | `POST /api/alerts/{id}/dismiss` | Clears it from the queue. It will not be re-alerted. |

**Read the state.** `GET /api/projects/{project_id}/monitor` returns watches
(with `last_checked`) and outstanding alerts, each carrying its similarity
`score` so you can see *how* related the Monitor thought it was.

## What it gives you

- **You stop re-running the same searches.** The corpus grows toward your open
  questions instead of you periodically going fishing.
- **Nothing is surfaced twice.** Between corpus dedup and alert dedup, an alert
  in your queue is genuinely something you have not seen.
- **A relevance score you can calibrate against.** After a few checks you learn
  where your field sits — if 0.45 is mostly noise for your topic, tighten the
  watch phrasing rather than raising a threshold.
- **It is free to run.** No LLM calls, local embeddings.

## Limits worth knowing

- **Nothing is automatic.** There is no scheduler. A check happens when you (or
  something you wire up) call it. If you want it daily, run the endpoint from
  cron.
- **Adding a paper does not update an existing report.** Reports are artefacts of
  the corpus at the moment they were assembled. If new work matters to a
  published conclusion, run the question again — and the difference between the
  two reports is itself the finding.
- **8 alerts per watch per check** is a hard cap, as is 12 results per source.
  A very broad watch will be truncated; several narrow watches beat one wide one.
- **The 0.42 threshold and the caps are constants in `app/services/monitor.py`**
  (`SCORE_THRESHOLD`, `MAX_PER_WATCH`), not environment settings.

## Email delivery

If SMTP is configured, alerts can be delivered by mail:

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=Veriscope <no-reply@veriscope.app>
APP_BASE_URL=https://your-deployment
```

## Related

- [Screening](#/docs/features/screening) — the same "you decide what enters the corpus" principle, at run time.
- [Bring your own papers](#/docs/how-to/bring-your-own-papers)
- [The research funnel](#/docs/explanation/funnel)
