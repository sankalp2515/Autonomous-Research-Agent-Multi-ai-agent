"""Verification-gate threshold calibration harness (audit item A3).

Runs the REAL gate over a labeled boundary set (evals/calibration_set.json) with
NLI ENABLED, and reports:

  * the confusion matrix at the SHIPPED thresholds — with false-ACCEPTS
    (unsupported claims that verified) called out first, because a false accept
    is a silently-wrong "verified" result, the one failure this product exists
    to prevent;
  * a per-category breakdown, so you can see WHICH boundary leaks;
  * a sweep over the contradiction / strong-neutral / quote-fuzzy thresholds,
    showing false-accept and false-reject counts at each operating point;
  * a what-if for ENFORCING nli_entailment_threshold (currently reserved / not
    wired), so the cost of turning it on is measured before anyone does.

This needs the local ML stack (pip install .[ml], ML_NLI_ENABLED=true) but NO
database, Redis or Qdrant — the gate verifies against an in-memory chunk map.

Usage:  python -m evals.calibrate
Exit:   0 if zero false-accepts at shipped thresholds, else 1 (wire into CI as a
        soft gate once the thresholds are trusted).
"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.ml.local_models import nli_available
from app.verification.gate import ClaimInput, verify_claims


def _load() -> list[dict]:
    data = json.loads((Path(__file__).parent / "calibration_set.json").read_text("utf-8"))
    return data["cases"]


async def _run_cases(cases: list[dict]) -> list[dict]:
    """Verify every case once; return per-case gate output joined to the label."""
    out = []
    for c in cases:
        report = await verify_claims(
            [ClaimInput(c["claim"], "c1", c["quote"])], {"c1": c["chunk"]}
        )
        r = report.results[0]
        ev = r.evidence
        out.append({
            **c,
            "verified": r.verified,
            "reason": r.reason,
            "nli_label": ev.nli_label if ev else "n/a",
            "nli_score": round(ev.nli_score, 3) if ev else 0.0,
            "quote_method": ev.quote_match.method if ev else "none",
            "quote_score": round(ev.quote_match.score, 3) if ev else 0.0,
        })
    return out


def _confusion(rows: list[dict]) -> dict:
    fa = [r for r in rows if not r["should_verify"] and r["verified"]]   # false accept
    fr = [r for r in rows if r["should_verify"] and not r["verified"]]   # false reject
    tp = [r for r in rows if r["should_verify"] and r["verified"]]
    tn = [r for r in rows if not r["should_verify"] and not r["verified"]]
    return {"false_accept": fa, "false_reject": fr, "tp": tp, "tn": tn}


def _print_confusion(rows: list[dict]) -> dict:
    conf = _confusion(rows)
    n_sup = sum(1 for r in rows if r["should_verify"])
    n_uns = len(rows) - n_sup
    print(f"\n  supported={n_sup}  unsupported={n_uns}  total={len(rows)}")
    print(f"  false_accept (shipped an UNSUPPORTED claim): {len(conf['false_accept'])}"
          f"   <-- must be 0")
    print(f"  false_reject (refused a SUPPORTED claim):    {len(conf['false_reject'])}")
    if conf["false_accept"]:
        print("\n  FALSE ACCEPTS:")
        for r in conf["false_accept"]:
            print(f"    [{r['id']}] {r['category']} — nli={r['nli_label']}:{r['nli_score']} "
                  f"quote={r['quote_method']}:{r['quote_score']}\n      claim: {r['claim']}")
    if conf["false_reject"]:
        print("\n  FALSE REJECTS:")
        for r in conf["false_reject"]:
            print(f"    [{r['id']}] {r['category']} — reason={r['reason']} "
                  f"nli={r['nli_label']}:{r['nli_score']} quote={r['quote_method']}:{r['quote_score']}"
                  f"\n      claim: {r['claim']}")
    return conf


def _print_by_category(rows: list[dict]) -> None:
    print("\n  Per-category (correct / total):")
    cats: dict[str, list[dict]] = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(r)
    for cat, rs in sorted(cats.items()):
        correct = sum(1 for r in rs if r["verified"] == r["should_verify"])
        print(f"    {cat:28s} {correct}/{len(rs)}")


async def _sweep(cases: list[dict]) -> None:
    """Re-run the whole set at each operating point. Mutates the cached settings
    singleton in place, then restores it."""
    settings = get_settings()
    orig = (settings.nli_contradiction_threshold,
            settings.nli_neutral_reject_threshold,
            settings.quote_fuzzy_threshold)

    print("\n=== THRESHOLD SWEEP (false_accept / false_reject) ===")
    print("  contradiction bar (lower = stricter on contradictions):")
    for t in (0.30, 0.40, 0.50, 0.60):
        settings.nli_contradiction_threshold = t
        rows = await _run_cases(cases)
        c = _confusion(rows)
        print(f"    {t:.2f} -> FA={len(c['false_accept'])}  FR={len(c['false_reject'])}")
    settings.nli_contradiction_threshold = orig[0]

    print("  strong-neutral reject bar (lower = stricter on out-of-context):")
    for t in (0.70, 0.80, 0.85, 0.90):
        settings.nli_neutral_reject_threshold = t
        rows = await _run_cases(cases)
        c = _confusion(rows)
        print(f"    {t:.2f} -> FA={len(c['false_accept'])}  FR={len(c['false_reject'])}")
    settings.nli_neutral_reject_threshold = orig[1]

    print("  quote fuzzy bar (higher = stricter on quote drift):")
    for t in (0.88, 0.92, 0.95, 0.98):
        settings.quote_fuzzy_threshold = t
        rows = await _run_cases(cases)
        c = _confusion(rows)
        print(f"    {t:.2f} -> FA={len(c['false_accept'])}  FR={len(c['false_reject'])}")
    settings.quote_fuzzy_threshold = orig[2]

    (settings.nli_contradiction_threshold,
     settings.nli_neutral_reject_threshold,
     settings.quote_fuzzy_threshold) = orig


def _entailment_whatif(rows: list[dict], tau: float) -> None:
    """What ENFORCING nli_entailment_threshold would do, computed from the NLI
    scores we already have — no re-run. A claim would additionally be REJECTED
    unless it is labeled 'entailment' with score >= tau."""
    def would_pass_entailment(r: dict) -> bool:
        return r["nli_label"] == "entailment" and r["nli_score"] >= tau

    new_fa = [r for r in rows if not r["should_verify"] and r["verified"]
              and would_pass_entailment(r)]
    caught = [r for r in rows if not r["should_verify"] and r["verified"]
              and not would_pass_entailment(r)]
    new_fr = [r for r in rows if r["should_verify"] and r["verified"]
              and not would_pass_entailment(r)]
    print(f"\n=== WHAT-IF: enforce entailment >= {tau:.2f} (currently NOT enforced) ===")
    print(f"  false-accepts this WOULD catch: {len(caught)}")
    print(f"  supported claims it WOULD newly reject (added false-rejects): {len(new_fr)}")
    print(f"  false-accepts remaining after enforcement: {len(new_fa)}")
    if new_fr:
        for r in new_fr:
            print(f"    would reject [{r['id']}] {r['category']} "
                  f"(nli={r['nli_label']}:{r['nli_score']})")


async def run() -> int:
    from app.core.logging import configure_logging
    configure_logging("WARNING", "console")

    if not nli_available():
        print("ML_NLI_ENABLED is off — calibration needs the NLI model.\n"
              "Run with: pip install .[ml] and ML_NLI_ENABLED=true", file=sys.stderr)
        return 2

    cases = _load()
    settings = get_settings()
    print("=== GATE CALIBRATION @ shipped thresholds ===")
    print(f"  contradiction>={settings.nli_contradiction_threshold} "
          f"neutral_reject>={settings.nli_neutral_reject_threshold} "
          f"quote_fuzzy>={settings.quote_fuzzy_threshold} "
          f"entailment_threshold={settings.nli_entailment_threshold} (reserved)")

    rows = await _run_cases(cases)
    conf = _print_confusion(rows)
    _print_by_category(rows)
    await _sweep(cases)
    _entailment_whatif(rows, settings.nli_entailment_threshold)

    print("\n=== SUMMARY ===")
    fa = len(conf["false_accept"])
    print(f"  false_accepts at shipped thresholds: {fa}")
    print("  A non-zero false-accept count means the gate can ship an unsupported\n"
          "  claim as 'verified' — investigate before trusting these thresholds.")
    return 0 if fa == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
