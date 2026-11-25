"""Screening vs a published systematic review — the humans' decisions, not ours.

WHY THIS EXISTS. Every downstream number in a report is conditional on the
corpus, and the corpus is whatever the screen let through. A screen that drops
a fifth of the studies a human review included produces a report that is
perfectly grounded and quietly unrepresentative — and no gate downstream can
see it, because the missing papers never arrive. Screening recall is the
number a systematic reviewer asks for first, and the one an evidence-synthesis
tool most often does not publish.

GOLD. A review's candidate pool with the reviewers' own include/exclude labels,
in the ASReview/SYNERGY layout (title, abstract, label_included). The shipped
protocol is SYNERGY's Hall_2012: "A Systematic Literature Review on Fault
Prediction Performance in Software Engineering" (IEEE TSE, 2012), 8,793
records, 104 marked included. The labels are SYNERGY's reconstruction of that
review (collected by Yu et al., doi 10.1007/s10664-017-9587-0); the review
itself reports 208 studies, so this is SYNERGY's label set, not the paper's
full list. The protocol file carries the review's PUBLISHED criteria (Table 2),
and those are what the screen is given — the question is whether, applying the
same rules to the same abstracts, it reaches the humans' decisions.

WHAT IS TESTED. The real `nodes._screen_papers`, unmodified: same prompt, same
batching, same failure handling, same 0.5 keep threshold. The scores the model
returned are recorded on the way past (a read-only wrapper) for the sweep.

SAMPLING AND WHAT IT DOES TO EACH NUMBER
  * Every included record is screened, so RECALL is measured on the whole
    positive class, not estimated.
  * Excludes are a seeded random sample. SPECIFICITY from a simple random
    sample of negatives is an unbiased estimate of the population value, and
    is reported with its interval.
  * PRECISION depends on prevalence, which the sample distorts on purpose. It
    is therefore reported re-weighted to the review's true prevalence, and
    labelled as such. The raw sample precision is never printed as if it were
    the population's.
  * WSS@recall (Cohen et al., 2006) — the share of screening work saved at the
    recall actually achieved — is computed on the population scale.

TWO CAVEATS THAT TRAVEL WITH EVERY NUMBER
  * The labels are FINAL inclusions (after full-text reading). Some included
    studies cannot be identified from the abstract alone, so title/abstract
    recall below 100% is partly irreducible. It is the conservative direction.
  * The 95% recall figure printed beside the result is the conventional target
    in screening-automation research (it is the R in WSS@95). It is a yardstick,
    not a standard Veriscope has been certified against.

USAGE
    python -m evals.screening_bench --protocol evals/protocols/hall_2012.json
    python -m evals.screening_bench --protocol ... --negatives 200 --seed 7 --json out.json

Needs LLM keys (one call per 15 records). Data is fetched separately and is
never committed: SYNERGY abstracts may not be republished in plaintext.
"""

import argparse
import asyncio
import csv
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from evals.stats import fmt, rate

ROOT = Path(__file__).parent


@dataclass
class Record:
    """The shape `_screen_papers` reads from a search hit."""
    record_id: str
    title: str
    abstract: str
    year: int | None
    label: int
    citation_count: int = 0
    source: str = "review"     # not "arxiv": no pool interleaving applies
    url: str = ""
    doi: str = ""


def load_records(path: Path) -> list[Record]:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            title = (r.get("title") or "").strip()
            if not title:
                continue
            year = r.get("publication_year") or r.get("year") or ""
            out.append(Record(
                record_id=r.get("openalex_id") or r.get("record_id") or title,
                title=title, abstract=(r.get("abstract") or "").strip(),
                year=int(year) if str(year).isdigit() else None,
                label=int(r.get("label_included") or 0),
                doi=r.get("doi") or ""))
    return out


def sample(records: list[Record], negatives: int, seed: int) -> list[Record]:
    """All positives + a seeded simple random sample of negatives, shuffled so
    batch position carries no label signal (the prompt numbers candidates)."""
    pos = [r for r in records if r.label]
    neg = [r for r in records if not r.label]
    rng = random.Random(seed)
    chosen = pos + (rng.sample(neg, negatives) if 0 < negatives < len(neg) else neg)
    rng.shuffle(chosen)
    return chosen


def metrics(screened: list[Record], kept_ids: set[str], population: int,
            population_pos: int) -> dict:
    """Population-scale screening metrics from a positives-complete sample."""
    pos = [r for r in screened if r.label]
    neg = [r for r in screened if not r.label]
    tp = sum(1 for r in pos if r.record_id in kept_ids)
    tn = sum(1 for r in neg if r.record_id not in kept_ids)
    rec = rate(tp, len(pos))
    spec = rate(tn, len(neg))
    out = {"sample": len(screened), "sample_pos": len(pos), "sample_neg": len(neg),
           "population": population, "population_pos": population_pos,
           "recall": rec, "specificity": spec,
           "missed": [{"title": r.title, "year": r.year, "doi": r.doi}
                      for r in pos if r.record_id not in kept_ids]}
    if rec["n"] and spec["n"] and population:
        prev = population_pos / population
        r_, s_ = rec["rate"], spec["rate"]
        denom = r_ * prev + (1 - s_) * (1 - prev)
        out["precision_at_prevalence"] = round(r_ * prev / denom, 4) if denom else None
        # The point estimate is not quotable on its own: 0 false positives in a
        # 200-record sample gives specificity 1.0 and therefore "100% precision",
        # while the specificity interval's lower end is ~98% — which at ~1%
        # prevalence means precision could be as low as a third. So the floor is
        # reported next to it, from the specificity lower bound.
        s_lo = spec["ci95"][0]
        d_lo = r_ * prev + (1 - s_lo) * (1 - prev)
        out["precision_at_prevalence_floor"] = round(r_ * prev / d_lo, 4) if d_lo else None
        # WSS@R = (TN + FN)/N - (1 - R), with TN scaled to the population.
        tn_pop = s_ * (population - population_pos)
        fn_pop = (1 - r_) * population_pos
        out["wss_at_recall"] = round((tn_pop + fn_pop) / population - (1 - r_), 4)
        out["records_to_read_per_100"] = round(100 * (1 - (tn_pop + fn_pop) / population), 1)
    return out


def threshold_sweep(screened: list[Record], scores: dict[str, float], population: int,
                    population_pos: int) -> list[dict]:
    """What the same verdicts would give at other keep thresholds. Read off the
    scores the model returned; no extra calls. Informational only."""
    rows = []
    for t in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        kept = {rid for rid, s in scores.items() if s >= t}
        m = metrics(screened, kept, population, population_pos)
        rows.append({"threshold": t, "recall": m["recall"]["rate"],
                     "specificity": m["specificity"]["rate"],
                     "wss": m.get("wss_at_recall")})
    return rows


async def screen(protocol: dict, records: list[Record]) -> tuple[set[str], dict[str, float], dict]:
    """Drive the production screen. Returns (kept record ids, model scores by
    record id, the state it left behind)."""
    from app.agents import nodes
    from app.agents.state import new_state

    state = new_state("screening-bench", "screening-bench", protocol["question"])
    state["evidence_schema"] = {"screening_criteria": protocol["criteria"]}
    # `_screen_papers` re-ranks candidates before numbering them, so a verdict's
    # index is only meaningful against the prompt that carried it. Each index is
    # resolved through that prompt's own "[i] (...) title — abstract" line.
    by_title: dict[str, str] = {r.title: r.record_id for r in records}
    line = re.compile(r"^\[(\d+)\] \([^)]*\) (.*?) — ", re.M)
    scores: dict[str, float] = {}
    real = nodes.complete_json

    # Per-record outcome, so a miss can be attributed: the model judged it out,
    # the model returned NO verdict for it, or the call that carried it failed.
    # Also: verdicts whose index was NOT in the prompt that produced them. The
    # production keep-set is built from every batch's indices against the
    # whole candidate list, so such a verdict decides a paper that batch never
    # showed the model.
    verdicts: dict[str, dict] = {}
    sent: set[str] = set()
    call_failed: set[str] = set()
    foreign: list[dict] = []

    async def observing(step, prompt, schema, *a, **kw):
        if step != "screen":
            return await real(step, prompt, schema, *a, **kw)
        titles = {int(i): t for i, t in line.findall(prompt)}
        ids = {i: by_title.get(t) for i, t in titles.items()}
        sent.update(r for r in ids.values() if r)
        try:
            res = await real(step, prompt, schema, *a, **kw)
        except Exception:
            call_failed.update(r for r in ids.values() if r)
            raise
        for p in getattr(res, "papers", []) or []:
            rid = ids.get(p.index)
            if rid is None:
                foreign.append({"index": p.index, "relevant": p.relevant,
                                "score": p.score, "batch_indices": sorted(ids)})
                continue
            call_failed.discard(rid)     # a retry answered it
            s = float(p.score if p.relevant else min(p.score, 0.49))
            scores[rid] = max(scores.get(rid, 0.0), s)
            verdicts[rid] = {"relevant": p.relevant, "score": p.score,
                             "failed_criterion": p.failed_criterion, "reason": p.reason}
        return res

    # Which provider answered. A screening number without the model behind it
    # cannot be reproduced, and the router fails over silently by design.
    from app.llm import router
    real_complete = router.complete
    providers: dict[str, int] = {}

    async def counting(*a, **kw):
        res = await real_complete(*a, **kw)
        providers[res.provider] = providers.get(res.provider, 0) + 1
        return res

    nodes.complete_json = observing
    router.complete = counting
    try:
        kept = await nodes._screen_papers(state, records, protocol["objective"],
                                          protocol.get("field", ""), 0)
    finally:
        nodes.complete_json = real
        router.complete = real_complete
    state["bench_providers"] = providers
    state["bench_verdicts"] = verdicts
    state["bench_no_verdict"] = sorted(sent - set(verdicts) - call_failed)
    state["bench_call_failed"] = sorted(call_failed - set(verdicts))
    state["bench_foreign_verdicts"] = foreign
    return {r.record_id for r in kept}, scores, state


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", default=str(ROOT / "protocols" / "hall_2012.json"))
    ap.add_argument("--negatives", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--limit", type=int, default=0, help="cap the sample (smoke run)")
    ap.add_argument("--json")
    ap.add_argument("--shared-cache", action="store_true",
                    help="use the real Redis LLM cache (reruns become free but replay old verdicts)")
    args = ap.parse_args()

    from app.core.config import get_settings
    from app.core.logging import configure_logging
    configure_logging("WARNING", "console")
    if not args.shared_cache:
        # An isolated in-memory Redis: no LLM response cached by an earlier run
        # (or an earlier version of the prompt) can answer for this one, so the
        # number describes the model as it behaves NOW. Rate-limit buckets and
        # token counters live here too; nothing else in the screen reads Redis.
        import fakeredis

        from app.stores import redis_store
        redis_store._client = fakeredis.FakeAsyncRedis(decode_responses=True)

    protocol = json.loads(Path(args.protocol).read_text("utf-8"))
    data = (Path(args.protocol).parent / protocol["records"]).resolve()
    if not data.exists():
        raise SystemExit(f"records not found: {data} (see {args.protocol} 'fetch')")
    records = load_records(data)
    population, population_pos = len(records), sum(r.label for r in records)
    chosen = sample(records, args.negatives, args.seed)
    if args.limit:
        chosen = chosen[:args.limit]

    settings = get_settings()
    if len(chosen) > settings.screen_max_candidates:
        raise SystemExit(
            f"sample of {len(chosen)} exceeds screen_max_candidates="
            f"{settings.screen_max_candidates}; the overflow would be excluded "
            "unscreened and counted as misses. Lower --negatives.")

    t0 = time.time()
    kept, scores, state = await screen(protocol, chosen)
    elapsed = time.time() - t0
    failed = (state.get("exclusion_counts") or {}).get("screen_failed", 0)
    if failed == len(chosen):
        print("ERROR: every screening batch failed (provider/keys?); nothing was measured.")
        return 1
    # The recorded scores must reproduce the production keep-set at the
    # production threshold, or the sweep below describes some other screen.
    # Foreign-index verdicts are the one known reason they may not: production
    # applies them, the bench (correctly) cannot attribute them.
    foreign = state.get("bench_foreign_verdicts", [])
    mine = {rid for rid, s in scores.items() if s >= 0.5}
    if scores and mine != kept and not foreign:
        print("ERROR: recorded scores do not reproduce the production keep decision.")
        return 1
    if foreign:
        print(f"DEFECT: {len(foreign)} verdict(s) carried an index that was not in "
              "the batch that returned them; production applied them to papers that "
              f"batch never showed the model. Keep-set differs on {len(mine ^ kept)} record(s).")
    m = metrics(chosen, kept, population, population_pos)
    sweep = threshold_sweep(chosen, scores, population, population_pos) if scores else []

    print(f"=== Screening vs {protocol['name']} ===")
    print(f"population {population} records, {population_pos} included "
          f"(prevalence {population_pos / population:.2%}); screened sample {m['sample']} "
          f"= all {m['sample_pos']} included + {m['sample_neg']} sampled excludes (seed {args.seed})")
    if failed:
        print(f"WARNING: {failed} records were in batches whose screening call FAILED; "
              "they count as excluded, exactly as production treats them.")
    print(f"  recall (sensitivity)       : {fmt(m['recall'])}    [conventional target 95%]")
    print(f"  specificity                : {fmt(m['specificity'])}")
    if "precision_at_prevalence" in m:
        print(f"  precision @ true prevalence: {m['precision_at_prevalence']:.1%}, floor "
              f"{m['precision_at_prevalence_floor']:.1%} at the specificity CI's lower end "
              "(re-weighted, see docstring)")
        print(f"  WSS @ achieved recall      : {m['wss_at_recall']:.1%}  "
              f"(~{m['records_to_read_per_100']} of every 100 records would still need a human read)")
    # Attribute every miss. Only the first kind is the model disagreeing with
    # the reviewers; the other two are Veriscope failing to assess the paper —
    # which production records identically (excluded), and that is the point.
    verdicts = state.get("bench_verdicts", {})
    no_verdict = set(state.get("bench_no_verdict", []))
    call_failed = set(state.get("bench_call_failed", []))
    by_id = {r.record_id: r for r in chosen}

    def cause(rid: str) -> str:
        return ("judged_out" if rid in verdicts else
                "no_verdict_returned" if rid in no_verdict else
                "screen_call_failed" if rid in call_failed else "not_sent")

    missed = [r for r in chosen if r.label and r.record_id not in kept]
    m["miss_breakdown"] = {}
    for r in missed:
        m["miss_breakdown"][cause(r.record_id)] = m["miss_breakdown"].get(cause(r.record_id), 0) + 1
    m["missed"] = [{"title": r.title, "year": r.year, "doi": r.doi, "cause": cause(r.record_id),
                    **verdicts.get(r.record_id, {})} for r in missed]
    m["unassessed_records"] = {
        "no_verdict_returned": len(no_verdict), "screen_call_failed": len(call_failed),
        "of_which_included": sum(1 for rid in no_verdict | call_failed if by_id[rid].label)}
    m["foreign_index_verdicts"] = len(foreign)
    if missed:
        print(f"\n  included studies the screen EXCLUDED ({len(missed)}), by cause: "
              f"{m['miss_breakdown']}")
        for r in m["missed"][:25]:
            why = (f"{r.get('failed_criterion') or '-'} (score {r.get('score', 0):.2f}): "
                   f"{r.get('reason', '')}" if r["cause"] == "judged_out" else r["cause"])
            print(f"    - ({r['year']}) {r['title'][:90]}\n        {why[:170]}")
    print(f"\n  records never assessed: {m['unassessed_records']}")
    if sweep:
        print("\n  keep-threshold sweep (same verdicts, informational):")
        for row in sweep:
            print(f"    >= {row['threshold']:.1f}: recall {row['recall']:.1%}  "
                  f"specificity {row['specificity']:.1%}")
    print(f"\n{elapsed:.0f}s, {state.get('llm_calls_used', 0)} screening calls, "
          f"answered by {state.get('bench_providers') or 'unknown'}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "benchmark": "screening", "protocol": protocol["name"],
            "seed": args.seed, "negatives": args.negatives, "metrics": m,
            "sweep": sweep, "screen_failed_records": failed,
            "llm_calls": state.get("llm_calls_used", 0), "seconds": round(elapsed),
            "providers": state.get("bench_providers", {}),
        }, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
