"""How much do the synthesis thresholds actually decide? (remaining item 5)

The strength classes, the disagreement band and the gap shares are judgement
calls stated in code — 5/3/2 studies, 10% relative, 34%/60% coverage. Judgement
is fine; judgement nobody has probed is not. If moving a threshold one notch
reclassifies half the corpus, the number is doing more work than the evidence and
should be argued about openly. If almost nothing moves, the numbers are safely
in a plateau and the honest thing is to say so rather than imply calibration
nobody performed.

This harness reports that sensitivity over real matrices. It does not choose
thresholds — there is no labelled ground truth for "correctly classified as
moderately supported", so an optimiser here would be fitting noise. It tells you
which knobs matter.

    python -m evals.threshold_sensitivity --report <report_id>
    python -m evals.threshold_sensitivity --matrix path/to/replay.json
"""

import argparse
import asyncio
import json
import sys
from collections import Counter

from app.agents import synthesis
from app.core.logging import configure_logging


def _classes(matrix: list[dict]) -> dict[str, str]:
    out = synthesis.synthesize(matrix)
    return {d["dimension"]: d["state"] for d in out["dimensions"]}


def _sweep(matrix: list[dict], name: str, values: list) -> list[dict]:
    """Re-run the synthesis with one constant moved, and report what changed."""
    base_val = getattr(synthesis, name)
    base = _classes(matrix)
    rows = []
    try:
        for v in values:
            setattr(synthesis, name, v)
            got = _classes(matrix)
            changed = {k: (base[k], got.get(k)) for k in base if got.get(k) != base[k]}
            gaps = len(synthesis.synthesize(matrix)["gaps"])
            rows.append({"value": v, "changed": len(changed), "gaps": gaps,
                         "examples": [f"{k}: {a} -> {b}" for k, (a, b) in
                                      list(changed.items())[:3]]})
    finally:
        setattr(synthesis, name, base_val)
    return rows


async def _matrix_from_report(report_id: str) -> list[dict]:
    from app.db.models import Report
    from app.db.session import session_scope
    async with session_scope() as s:
        r = await s.get(Report, report_id)
        if r is None:
            raise SystemExit(f"no report {report_id}")
        return (r.confidence or {}).get("evidence_matrix") or []


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="")
    ap.add_argument("--matrix", default="", help="an extraction_ab replay json")
    args = ap.parse_args()
    configure_logging("WARNING", "console")

    if args.matrix:
        matrix = json.load(open(args.matrix, encoding="utf-8")).get("matrix", [])
    elif args.report:
        matrix = await _matrix_from_report(args.report)
    else:
        raise SystemExit("pass --report or --matrix")

    base = synthesis.synthesize(matrix)
    print(json.dumps({
        "studies": base["studies_total"],
        "dimensions": len(base["dimensions"]),
        "baseline_states": dict(Counter(d["state"] for d in base["dimensions"])),
        "baseline_gaps": len(base["gaps"]),
    }, indent=2))

    sweeps = {
        "STRONG_MIN_STUDIES": [3, 4, 5, 6, 8],
        "MODERATE_MIN_STUDIES": [2, 3, 4],
        "DISAGREEMENT_RELATIVE": [0.05, 0.10, 0.20, 0.35],
        "DISAGREEMENT_ABSOLUTE_PP": [0.0, 1.0, 2.0, 5.0],
        "UNDER_MEASURED_SHARE": [0.20, 0.34, 0.50],
        "WELL_COVERED_SHARE": [0.50, 0.60, 0.75],
    }
    print("\nthreshold                  value    dims reclassified   gaps")
    for name, values in sweeps.items():
        for row in _sweep(matrix, name, values):
            mark = "  <- shipped" if row["value"] == getattr(synthesis, name) else ""
            print(f"{name:26s} {str(row['value']):7s} {row['changed']:>6d}"
                  f"{'':>12s}{row['gaps']:>4d}{mark}")
            for ex in row["examples"]:
                print(f"{'':34s}{ex}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
