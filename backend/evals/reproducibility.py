"""Run-to-run reproducibility: the same question, asked twice.

WHY THIS EXISTS. A review whose corpus, schema or conclusions change every time
it is re-run cannot be cited, because nobody — including its author — can say
which version is the review. PRISMA asks for a search a reader could repeat;
an LLM pipeline has to show how close a repeat actually comes. The design
already pins temperature 0 on the schema and the architect and keeps D
statements deterministic given a matrix; this measures what survives the parts
that are not (live search results, screening, extraction).

WHAT IS COMPARED (two GET /api/report/{id} bodies for the same question)
  corpus         Jaccard of included studies (by normalized title, so two
                 projects' separate Document rows still match)
  schema         Jaccard of required dimension names
  cells          on studies + dimensions BOTH runs audited: share of cells
                 given the same state
  values         on findings both runs extracted for the same study, axis,
                 metric and dataset: share with the same parsed value
  derived        Jaccard of D-statement texts
  sections       Jaccard of section headings (informational: the architect may
                 legitimately phrase a heading differently)

Each is a share with its denominator; none is folded into a single score.

USAGE
    python -m evals.reproducibility --a run1.json --b run2.json [--out diff.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())).strip()


def _jac(a: set, b: set) -> dict:
    u = a | b
    return {"shared": len(a & b), "union": len(u),
            "jaccard": round(len(a & b) / len(u), 4) if u else None,
            "only_a": sorted(a - b)[:10], "only_b": sorted(b - a)[:10]}


def _share(k: int, n: int) -> dict:
    return {"agree": k, "n": n, "rate": round(k / n, 4) if n else None}


def compare(a: dict, b: dict) -> dict:
    from app.agents.normalize import parse_quantity
    ca, cb = a.get("confidence") or {}, b.get("confidence") or {}
    ma = {_norm(r.get("title")): r for r in ca.get("evidence_matrix") or []}
    mb = {_norm(r.get("title")): r for r in cb.get("evidence_matrix") or []}
    da = {d.get("name") for d in (ca.get("evidence_schema") or {}).get("required_dimensions") or []}
    db = {d.get("name") for d in (cb.get("evidence_schema") or {}).get("required_dimensions") or []}

    cell_n = cell_k = val_n = val_k = 0
    disagreements = []
    for title in set(ma) & set(mb):
        ra, rb = ma[title], mb[title]
        cells_a, cells_b = ra.get("cells") or {}, rb.get("cells") or {}
        for dim in set(cells_a) & set(cells_b):
            cell_n += 1
            if cells_a[dim].get("state") == cells_b[dim].get("state"):
                cell_k += 1
            else:
                disagreements.append({"study": ra.get("title"), "dimension": dim,
                                      "a": cells_a[dim].get("state"), "b": cells_b[dim].get("state")})

        def keyed(row):
            out = {}
            for f in row.get("findings") or []:
                ctx = f.get("context") or {}
                k = (f.get("dimension", "").lower(), (f.get("metric") or "").lower(),
                     (ctx.get("dataset") or "").lower())
                q = parse_quantity(f.get("value") or "")
                if q.ok and all(k):
                    out.setdefault(k, set()).add(round(q.number, 6))
            return out
        fa, fb = keyed(ra), keyed(rb)
        for k in set(fa) & set(fb):
            val_n += 1
            val_k += bool(fa[k] & fb[k])

    sa = {s.get("text") for s in ca.get("derived_statements") or []}
    sb = {s.get("text") for s in cb.get("derived_statements") or []}
    ha = {_norm(s.get("heading")) for s in a.get("sections") or []}
    hb = {_norm(s.get("heading")) for s in b.get("sections") or []}
    return {
        "a": a.get("id"), "b": b.get("id"),
        "question_a": a.get("question"), "question_b": b.get("question"),
        "corpus": _jac(set(ma), set(mb)),
        "schema": _jac(da, db),
        "cells_same_state": _share(cell_k, cell_n),
        "values_same": _share(val_k, val_n),
        "derived": _jac(sa, sb),
        "sections": _jac(ha, hb),
        "cell_disagreements": disagreements[:25],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out")
    args = ap.parse_args()
    a = json.loads(Path(args.a).read_text("utf-8"))
    b = json.loads(Path(args.b).read_text("utf-8"))
    r = compare(a, b)
    if _norm(r["question_a"] or "") != _norm(r["question_b"] or ""):
        print("WARNING: the two reports answer different questions; this is not a repeat.")
    for k in ("corpus", "schema", "derived", "sections"):
        j = r[k]
        print(f"  {k:9} jaccard {j['jaccard']}  ({j['shared']} shared of {j['union']})")
    for k in ("cells_same_state", "values_same"):
        s = r[k]
        print(f"  {k:17} {s['rate']}  ({s['agree']}/{s['n']})")
    if args.out:
        Path(args.out).write_text(json.dumps(r, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
