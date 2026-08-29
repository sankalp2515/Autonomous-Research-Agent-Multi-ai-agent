Symptoms, causes and fixes — ordered by how often they actually happen.

## The run clock looks frozen

It should not. The clock is computed **server-side** against one reference `now`, and the
client ticks forward from it using a monotonic delta.

If it genuinely freezes, the client is re-deriving elapsed time from a timestamp instead
of using the server value. That path is a known trap: `DateTime(timezone=True)` loses its
tzinfo on SQLite, and reading that naive value as local time puts the clock out by hours.

## A run ended early with "budget exhausted" gaps

Check **which** budget ran out — the reason is named, not generic.

| Budget | Symptom | Fix |
| --- | --- | --- |
| Wall clock | Last sections gap out while LLM call count is low | Raise `RUN_MAX_WALL_SECONDS` (5400 is the sane floor for a ~28-paper corpus) |
| LLM calls | Call count at the cap | Raise `RUN_MAX_LLM_CALLS` |
| Regens | A specific section keeps failing the gate | Usually a retrieval problem, not a budget one |

A wall-clock truncation is not an evidence gap, and the report should not read as though
it were. If it does, that is a bug worth reporting.

## Most matrix cells say "extraction uncertain"

In order of likelihood:

1. **The corpus is abstract-only.** Papers without retrievable full text can never ground
   an absence. Check the funnel's `full_text_available` rung.
2. **Recovery is disabled or capped.** `EVIDENCE_RECOVERY_ENABLED=false` pushes every
   unresolved required cell to uncertain by design.
3. **Retrieval is missing the passages.** Benchmark it before tuning — see
   [Tune retrieval](#/docs/how-to/tune-retrieval).
4. **The schema vocabulary does not match the field.** Rephrase the question in the terms
   the literature uses.

## Every claim is being refused

- **NLI is off.** Check `ML_NLI_ENABLED` and that `[ml]` is installed. Without it,
  quote-match is the only gate — you would see the opposite symptom, so this is more
  likely a model-loading failure than a config one. Check the logs for the model download.
- **The quotes are being normalised.** Quote-match is verbatim; ligatures and hyphenation
  from PDF extraction are the usual culprits. `QUOTE_FUZZY_THRESHOLD` is 0.92.
- **The corpus does not support the question.** Sometimes refusal is correct. Check
  whether the chat surface refuses the same question.

## Search returns nothing from arXiv

Almost always a screening bug rather than a search one. If candidates are sorted globally
by `citation_count`, arXiv hits sort to the bottom and get cut, because `search_arxiv`
cannot populate that field. Screening must rank **within** each pool and interleave.
`tests/test_screening_pools.py` pins this.

## The API returns 503

The global queue is above `MAX_QUEUE_DEPTH`. This is deliberate load shedding. Scale
workers, or raise the threshold if the workers are genuinely keeping up.

## The API returns 401 on every call

The backend requires auth (`AUTH_DISABLED=false`) but the frontend build has no Supabase
keys, so there is no way to sign in. Rebuild the frontend with `VITE_SUPABASE_URL` and
`VITE_SUPABASE_ANON_KEY`. The app detects this case and shows a config notice rather than
an endless failure.

## Two workers are fighting over one run

Run exactly one worker from source. In compose, job claim is atomic and replicas are safe.
`tests/test_run_lock.py` covers the claim path.

## Progress events are the wrong colour

Every progress event is typed **at the publish site** with a `kind` — `stage`, `search`,
`ingest`, `corpus`, `extract`, `recover`, `verify`, `refuse`, `error`, `done`. The feed
groups and colours on `kind` alone. If a refusal renders as ordinary progress, a publish
site is missing its `kind`. That is a regression the tests fail on.

## The stepper snaps back to step one mid-run

The stepper must name the real graph nodes, `evidence_schema` included. An unlisted node
makes the stepper fail to match and reset.

## Related

- [Deploy to production](#/docs/how-to/deploy)
- [Configuration](#/docs/reference/configuration)
