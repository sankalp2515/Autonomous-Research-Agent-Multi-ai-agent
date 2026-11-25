"""The verification gate against SciFact — expert labels, not our own.

WHY THIS EXISTS. `calibrate.py` probes the gate with 12 hand-built boundary
cases. That says "no leak is visible at the boundaries we thought of", which is
not a number a reviewer can hold us to. SciFact (Wadden et al., EMNLP 2020) is
1.4K scientific claims written by experts against PubMed abstracts, each pair
labelled SUPPORT / CONTRADICT / not-enough-info, with the rationale sentences
marked. It is the standard public benchmark for exactly the question the gate
answers: does THIS source span support THIS claim?

WHAT IS TESTED. The real `verify_claims`, all three layers, on one in-memory
"chunk" per pair (the paper's title + abstract), with the claim as the claim
text. The quote is chosen the way a drafting model would choose it:

  SUPPORT     the first gold rationale sentence     → a correct gate VERIFIES
  CONTRADICT  the first gold rationale sentence     → a correct gate REFUSES
  NEI         the abstract sentence that overlaps   → a correct gate REFUSES
              the claim most (lexically)

CONTRADICT is the hard case and the one that matters: the quote is genuinely on
topic and verbatim, so layers 1-2 pass by construction and only the NLI layer
stands between the reader and a "verified" sentence the source contradicts.

WHAT IS NOT TESTED. Retrieval and drafting. Here the quote is handed to the
gate; in production a model picks it. So this measures the gate's DECISION
quality, which bounds — but is not — end-to-end report accuracy.

METHODOLOGY (so the number survives a reviewer)
  * Shipped thresholds are evaluated as-is. They were set before this eval
    existed; nothing here was tuned on dev.
  * The threshold sweep runs on TRAIN only. The best train operating point is
    then reported on DEV, once. Reporting a dev-tuned threshold on dev is the
    overfitting this harness exists to avoid.
  * Every rate carries n and a 95% Wilson interval (evals/stats.py).
  * The offline sweep re-implements the layer-3 decision; it is checked against
    the real gate's verdict on every case before any sweep number is printed.
  * The NLI model (MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli) was trained
    on MNLI / FEVER-NLI / ANLI, not on SciFact: this is out-of-domain for it,
    which is the situation it faces in production too.

DATA. CC BY-NC 2.0, not redistributed here. Fetch it once:
    python -m evals.fetch_data scifact

USAGE
    ML_NLI_ENABLED=true python -m evals.scifact_gate               # dev + sweep
    python -m evals.scifact_gate --json out/scifact.json
    python -m evals.scifact_gate --limit 40                         # smoke run

Exit code is 0 always: this is a measurement, and the release gate it informs
is a decision for a human reading the numbers (see docs/EVALUATION.md).
"""

import argparse
import asyncio
import json
import re
import sys
import time
from itertools import product
from pathlib import Path

from app.core.config import get_settings
from app.verification.gate import ClaimInput, verify_claims
from evals.stats import fmt, rate

DATA = Path(__file__).parent / "data" / "scifact" / "data"

_STOP = set("""a an the of in on for to and or with by from as at is are was were be been
being that this these those it its into than then which who whom whose not no can may
might will would should could has have had do does did""".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP}


def _best_overlap(claim: str, sentences: list[str]) -> str:
    """The abstract sentence a drafting model would most plausibly quote for an
    unsupported claim: the one sharing the most content words. Ties break to
    the earlier sentence, so the choice is deterministic."""
    cw = _words(claim)
    best, best_score = sentences[0], -1.0
    for s in sentences:
        sw = _words(s)
        score = len(cw & sw) / (len(cw | sw) or 1)
        if score > best_score:
            best, best_score = s, score
    return best


def build_cases(claims: list[dict], corpus: dict[int, dict]) -> list[dict]:
    """One case per (claim, cited document). Pure; tested without the data."""
    cases: list[dict] = []
    for c in claims:
        evidence = c.get("evidence") or {}
        for doc_id in c.get("cited_doc_ids") or []:
            doc = corpus.get(int(doc_id))
            if not doc or not doc.get("abstract"):
                continue
            sentences = [s.strip() for s in doc["abstract"] if s.strip()]
            if not sentences:
                continue
            chunk = f"{doc['title'].strip()}\n\n" + " ".join(sentences)
            sets = evidence.get(str(doc_id))
            if sets:
                label = sets[0]["label"]
                idx = sets[0]["sentences"][0]
                if idx >= len(doc["abstract"]):
                    continue
                quote = doc["abstract"][idx].strip()
            else:
                label = "NEI"
                quote = _best_overlap(c["claim"], sentences)
            if len(quote) < 12 or quote not in chunk:
                continue
            cases.append({
                "id": f"{c['id']}:{doc_id}", "claim_id": c["id"], "doc_id": int(doc_id),
                "label": label, "claim": c["claim"], "quote": quote, "chunk": chunk,
            })
    return cases


def _load(split: str) -> tuple[list[dict], dict[int, dict]]:
    if not (DATA / "corpus.jsonl").exists():
        raise SystemExit(
            f"SciFact not found at {DATA}. See the module docstring for the "
            "one-time download (python -m evals.fetch_data scifact).")
    corpus = {}
    for line in (DATA / "corpus.jsonl").read_text("utf-8").splitlines():
        d = json.loads(line)
        corpus[int(d["doc_id"])] = d
    claims = [json.loads(line) for line in
              (DATA / f"claims_{split}.jsonl").read_text("utf-8").splitlines()]
    return claims, corpus


async def run_gate(cases: list[dict], batch: int = 32) -> list[dict]:
    """The REAL gate, batched; each case gets its own chunk id so a quote can
    only ever match its own abstract (re-attribution cannot cross cases)."""
    out: list[dict] = []
    for start in range(0, len(cases), batch):
        part = cases[start:start + batch]
        lookup = {c["id"]: c["chunk"] for c in part}
        report = await verify_claims(
            [ClaimInput(c["claim"], c["id"], c["quote"]) for c in part], lookup)
        for c, r in zip(part, report.results):
            ev = r.evidence
            out.append({**c, "verified": r.verified, "reason": r.reason,
                        "nli_label": ev.nli_label if ev else "n/a",
                        "nli_score": round(ev.nli_score, 4) if ev else 0.0})
    return out


def full_probabilities(rows: list[dict]) -> None:
    """Attach all three NLI probabilities (the gate only keeps the argmax) so
    thresholds can be swept offline without re-running the model per point."""
    from app.ml.local_models import _infer_lock, _nli
    model = _nli()
    if model is None:
        return
    inputs = [{"text": r["chunk"][:2000], "text_pair": r["claim"][:1000]} for r in rows]
    with _infer_lock:
        batched = model(inputs, batch_size=16)
    for r, scores in zip(rows, batched):
        r["probs"] = {s["label"].lower(): round(s["score"], 5) for s in scores}


def decide(row: dict, contradiction: float, neutral: float, entail_min: float) -> bool | None:
    """Layer 3 as a pure function of the stored probabilities. With
    entail_min=0 this is exactly `gate._apply_nli`. Rows that never reached NLI
    (failed layers 1-2) keep their real verdict."""
    if row["reason"] in ("missing_chunk", "quote_mismatch", "unsupported_entity"):
        return False
    probs = row.get("probs")
    if not probs:
        return None
    label = max(probs, key=probs.get)
    score = probs[label]
    if label == "contradiction" and score >= contradiction:
        return False
    if label == "neutral" and score >= neutral:
        return False
    return probs.get("entailment", 0.0) >= entail_min


def score(rows: list[dict], verdict=lambda r: r["verified"]) -> dict:
    """Per-label outcomes. A 'false accept' is a verified CONTRADICT or NEI
    pair; a 'false reject' is a refused SUPPORT pair."""
    by = {lab: [r for r in rows if r["label"] == lab] for lab in ("SUPPORT", "CONTRADICT", "NEI")}
    verified = [r for r in rows if verdict(r)]
    unsupported = by["CONTRADICT"] + by["NEI"]
    return {
        "pairs": len(rows),
        "false_accept_contradict": rate(sum(1 for r in by["CONTRADICT"] if verdict(r)), len(by["CONTRADICT"])),
        "false_accept_nei": rate(sum(1 for r in by["NEI"] if verdict(r)), len(by["NEI"])),
        "false_accept_any": rate(sum(1 for r in unsupported if verdict(r)), len(unsupported)),
        "false_reject_support": rate(sum(1 for r in by["SUPPORT"] if not verdict(r)), len(by["SUPPORT"])),
        # Of the pairs the gate called verified, how many did experts label
        # SUPPORT. Depends on this set's label mix — reported, never headlined.
        "verified_precision": rate(sum(1 for r in verified if r["label"] == "SUPPORT"), len(verified)),
    }


def sweep(train: list[dict]) -> list[dict]:
    grid = product((0.3, 0.4, 0.5, 0.6), (0.5, 0.6, 0.7, 0.85), (0.0, 0.3, 0.5, 0.6, 0.7))
    points = []
    for c, n, e in grid:
        s = score(train, verdict=lambda r, c=c, n=n, e=e: bool(decide(r, c, n, e)))
        points.append({"contradiction": c, "neutral": n, "entail_min": e,
                       "fa": s["false_accept_any"]["rate"], "fr": s["false_reject_support"]["rate"]})
    return points


def _pick(points: list[dict], max_fr: float) -> dict | None:
    """Lowest false-accept rate whose false-reject cost stays within budget.
    A gate that refuses every SUPPORT claim has FA=0 and is useless; the budget
    is what keeps the sweep from 'winning' that way."""
    ok = [p for p in points if p["fr"] is not None and p["fr"] <= max_fr]
    return min(ok, key=lambda p: (p["fa"], p["fr"])) if ok else None


def _print(title: str, s: dict) -> None:
    print(f"\n{title}  ({s['pairs']} claim/abstract pairs)")
    print(f"  false accept, CONTRADICT : {fmt(s['false_accept_contradict'])}")
    print(f"  false accept, NEI        : {fmt(s['false_accept_nei'])}")
    print(f"  false accept, any        : {fmt(s['false_accept_any'])}")
    print(f"  false reject, SUPPORT    : {fmt(s['false_reject_support'])}")
    print(f"  precision of 'verified'  : {fmt(s['verified_precision'])}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="cap claims per split (smoke run)")
    ap.add_argument("--json", help="write per-case rows + summary here")
    ap.add_argument("--max-fr", type=float, default=0.35,
                    help="false-reject budget for the train sweep")
    ap.add_argument("--nli-model", help="evaluate a candidate NLI model instead of the "
                    "configured one (same harness, same cases: a like-for-like comparison)")
    args = ap.parse_args()

    settings = get_settings()
    if args.nli_model:
        # Before the first _nli() call, which caches the pipeline for the process.
        settings.nli_model = args.nli_model
    if not settings.ml_nli_enabled:
        raise SystemExit("ML_NLI_ENABLED must be true: this evaluates the NLI layer.")
    t0 = time.time()
    splits = {}
    for split in ("dev", "train"):
        claims, corpus = _load(split)
        if args.limit:
            claims = claims[:args.limit]
        cases = build_cases(claims, corpus)
        rows = await run_gate(cases)
        full_probabilities(rows)
        splits[split] = rows

    # The offline decision must reproduce the real gate before it may be swept.
    # The two passes score the same pairs in DIFFERENT batches, and padding in a
    # batched forward pass moves probabilities in the third decimal. A pair
    # sitting on a threshold can therefore flip between them — which is a real
    # property of the production gate (a borderline verdict depends on batch
    # composition), so it is measured and reported, not hidden. Any mismatch
    # that drift cannot explain stops the run.
    drift, borderline, unexplained = 0.0, [], []
    for rows in splits.values():
        for r in rows:
            probs = r.get("probs") or {}
            if r["nli_label"] in probs:
                drift = max(drift, abs(probs[r["nli_label"]] - r["nli_score"]))
            offline = decide(r, settings.nli_contradiction_threshold,
                             settings.nli_neutral_reject_threshold, 0.0)
            if offline in (None, r["verified"]):
                continue
            top = max(probs, key=probs.get) if probs else ""
            thr = {"contradiction": settings.nli_contradiction_threshold,
                   "neutral": settings.nli_neutral_reject_threshold}.get(top)
            near = thr is not None and abs(probs[top] - thr) <= 0.01
            label_flip = top != r["nli_label"] and abs(
                probs.get(r["nli_label"], 0) - probs.get(top, 0)) <= 0.01
            (borderline if near or label_flip else unexplained).append(r["id"])
    if unexplained:
        print(f"ERROR: offline decision disagrees with the real gate on {len(unexplained)} "
              f"cases not explained by batch numerics (e.g. {unexplained[:3]}); the sweep "
              "would describe some other gate.")
        return 1
    for rows in splits.values():          # sweep from the verdict the gate GAVE
        for r in rows:
            if r["id"] in borderline:
                r["borderline"] = True

    shipped = {k: score(v) for k, v in splits.items()}
    print("=== Verification gate vs SciFact (expert labels) ===")
    print(f"thresholds: contradiction>={settings.nli_contradiction_threshold}  "
          f"neutral>={settings.nli_neutral_reject_threshold}  entail_min=none (reserved)  "
          f"entity_check={settings.gate_entity_check_enabled}")
    print(f"batch numerics: max |score drift| between two batchings {drift:.4f}; "
          f"{len(borderline)} pair(s) flip verdict on it (borderline, see docstring)")
    _print("DEV (held out) - shipped thresholds", shipped["dev"])
    _print("TRAIN - shipped thresholds", shipped["train"])

    reasons: dict[str, int] = {}
    for r in splits["dev"]:
        if r["label"] != "SUPPORT" and r["verified"]:
            reasons[r["nli_label"]] = reasons.get(r["nli_label"], 0) + 1
    print(f"\n  dev false accepts by NLI argmax: {reasons or 'none'}")

    points = sweep(splits["train"])
    best = _pick(points, args.max_fr)
    held_out = None
    if best:
        held_out = score(splits["dev"], verdict=lambda r: bool(
            decide(r, best["contradiction"], best["neutral"], best["entail_min"])))
        print(f"\nBest TRAIN operating point with false-reject <= {args.max_fr:.0%}: "
              f"contradiction>={best['contradiction']} neutral>={best['neutral']} "
              f"entail_min>={best['entail_min']}  (train FA {best['fa']:.1%}, FR {best['fr']:.1%})")
        _print("DEV (held out) - that operating point, evaluated once", held_out)
    front: list[dict] = []
    for p in sorted(points, key=lambda p: (p["fr"], p["fa"])):
        if not front or p["fa"] < front[-1]["fa"] - 1e-9:
            front.append(p)
    print("\nTRAIN trade-off frontier (false reject -> false accept):")
    for p in front:
        print(f"  FR {p['fr']:.1%}  FA {p['fa']:.1%}   contradiction>={p['contradiction']} "
              f"neutral>={p['neutral']} entail_min>={p['entail_min']}")
    print(f"\n{time.time() - t0:.0f}s")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "benchmark": "scifact", "license": "CC BY-NC 2.0",
            "thresholds": {"contradiction": settings.nli_contradiction_threshold,
                           "neutral": settings.nli_neutral_reject_threshold,
                           "entity_check": settings.gate_entity_check_enabled},
            "nli_model": settings.nli_model,
            "batch_drift_max": round(drift, 5), "borderline_flips": borderline,
            "shipped": shipped, "train_sweep": points, "train_best": best,
            "dev_at_train_best": held_out,
            "dev_rows": [{k: v for k, v in r.items() if k != "chunk"} for r in splits["dev"]],
        }, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
