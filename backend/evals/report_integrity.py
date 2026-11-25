"""Publication-integrity audit for ONE finished report. Deterministic, no LLM.

WHY THIS EXISTS. The other evals measure the machinery on benchmarks. This one
reads a report a researcher is about to rely on, and checks the things a peer
reviewer, a methods editor, or a skeptical hiring panel would check first —
the small inconsistencies that cost a whole document its credibility:

  * a PRISMA ladder that grows somewhere it can only shrink;
  * "N screened" that does not equal screened-in + screened-out;
  * cell-state tallies that do not add up to the grid they describe;
  * a "not reported" cell published without the evidence of search the cell
    model requires (the rule CLAUDE.md says must never be relaxed);
  * a claim whose quote is no longer in the chunk it cites;
  * a D sentence that recomputation does not reproduce, that names no rows,
    that says more than its counts, or that prints a value no study reported;
  * two rows that are the same study (a preprint and its published version),
    which silently inflates every "N independent studies";
  * references a researcher cannot cite (no year/authors/link), duplicated, or
    outside the review's own year window;
  * a mostly-ungrounded report without the low-confidence banner.

Every check is a property the pipeline CLAIMS to guarantee. The audit turns each
claim into a test against a real artefact, so a regression shows up on the
report it damaged rather than in a unit test of a function nobody called.

USAGE
    python -m evals.report_integrity --json report.json   # GET /api/report/{id} body
    python -m evals.report_integrity --report <report_id> # straight from Postgres
Exit 1 if any ERROR-level finding; warnings are printed and returned.
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

_CELL_STATES = ("reported", "not_reported", "not_applicable", "extraction_uncertain")
_LADDER = ("discovered", "screened", "eligible", "ingested", "full_text_available",
           "extracted", "included_in_synthesis", "cited_in_report")
# Each pair must be non-increasing: the later stage is a subset of the earlier.
_LADDER_SUBSETS = (("discovered", "screened"), ("ingested", "full_text_available"),
                   ("ingested", "extracted"), ("extracted", "included_in_synthesis"),
                   ("ingested", "cited_in_report"))
# What a D sentence may never contain (CLAUDE.md, restraint). "better"/"worse"
# rank systems by desirability, which only an I sentence may do.
_D_BANNED = ("the field", "the literature", "suggests that", "more research is needed",
             " better", " worse", "outperform", "superior", "inferior")


def _issue(code: str, severity: str, message: str, **evidence) -> dict:
    return {"code": code, "severity": severity, "message": message,
            **({"evidence": evidence} if evidence else {})}


def _norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(a.split()), set(b.split())
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


# ── checks ────────────────────────────────────────────────────────────────

def check_funnel(conf: dict) -> list[dict]:
    out = []
    f = conf.get("funnel") or {}
    ladder = f.get("ladder") or {}
    for hi, lo in _LADDER_SUBSETS:
        a, b = ladder.get(hi), ladder.get(lo)
        if a and b is not None and b > a:
            out.append(_issue("F1", "error",
                              f"ladder grows from {hi} ({a}) to {lo} ({b}); a later stage "
                              "is a subset of an earlier one", stage=lo))
    s_in, s_out, s_all = f.get("screened_in"), f.get("screened_out"), f.get("screened")
    if s_in is not None and s_out is not None and s_all and s_in + s_out != s_all:
        out.append(_issue("F2", "error",
                          f"screened ({s_all}) != screened in ({s_in}) + screened out ({s_out})"))
    total = f.get("cells_total")
    if total:
        parts = sum(int(f.get(f"cells_{k}", 0) or 0) for k in
                    ("reported", "not_reported", "not_applicable", "uncertain"))
        if parts != total:
            out.append(_issue("F3", "error",
                              f"cell states sum to {parts} but cells_total is {total}"))
    return out


def check_sections(payload: dict) -> list[dict]:
    out = []
    conf = payload.get("confidence") or {}
    sections = payload.get("sections") or []
    owner: dict[str, str] = {}
    ids: list[str] = []
    for s in sections:
        cids = list(s.get("claim_ids") or [])
        ids.extend(cids)
        for cid in cids:
            if cid in owner:
                out.append(_issue("C1", "error", "one claim is shown in two sections "
                                  "(counted twice)", claim_id=cid,
                                  sections=[owner[cid], s.get("heading")]))
            owner.setdefault(cid, s.get("heading", ""))
        if s.get("status") == "verified" and not cids:
            out.append(_issue("C2", "error", "section marked verified with no claims",
                              section=s.get("heading")))
        if s.get("status") == "gap":
            if cids:
                out.append(_issue("C3", "error", "gap section ships claims",
                                  section=s.get("heading")))
            if not (s.get("gap_note") or "").strip():
                out.append(_issue("C4", "warn", "gap section has no gap note telling the "
                                  "reader why", section=s.get("heading")))
        shown = {c.get("claim_id") for c in s.get("claims") or []}
        for cid in cids:
            if "claims" in s and cid not in shown:
                out.append(_issue("C5", "error", "section lists a claim the report cannot "
                                  "load (deleted or never persisted)", claim_id=cid))
    verified_sections = sum(1 for s in sections if s.get("status") == "verified")
    if conf.get("sections_verified") is not None and conf["sections_verified"] != verified_sections:
        out.append(_issue("F6", "error",
                          f"header says {conf['sections_verified']} sections grounded; "
                          f"{verified_sections} are"))
    f = conf.get("funnel") or {}
    if f.get("claims_verified") is not None and f["claims_verified"] != len(ids):
        out.append(_issue("F5", "error",
                          f"funnel says {f['claims_verified']} verified claims; sections hold {len(ids)}"))
    comp = conf.get("composition") or {}
    if comp.get("verified") is not None and comp["verified"] != len(ids):
        out.append(_issue("F5", "error",
                          f"kicker reads {comp['verified']} verified; sections hold {len(ids)}"))
    if comp.get("derived") is not None and comp["derived"] != len(conf.get("derived_statements") or []):
        out.append(_issue("F5", "error",
                          f"kicker reads {comp['derived']} derived; report carries "
                          f"{len(conf.get('derived_statements') or [])}"))
    if sections and verified_sections / len(sections) < 0.5 and not conf.get("low_confidence"):
        out.append(_issue("S1", "error", f"only {verified_sections}/{len(sections)} sections "
                          "grounded but the low-confidence banner is off"))
    return out


def check_evidence(payload: dict, fuzzy: float = 0.92) -> list[dict]:
    """Re-verify every shipped quote against the chunk it cites, with the
    production matcher. The gate checked this once at draft time; a re-chunk,
    a tombstoned document or an id-translation bug can break it afterwards."""
    from app.verification.quote_match import match_quote
    out = []
    for s in payload.get("sections") or []:
        for c in s.get("claims") or []:
            evs = c.get("evidence") or []
            if not evs:
                out.append(_issue("C5", "error", "claim has no evidence span",
                                  claim_id=c.get("claim_id")))
            for ev in evs:
                doc = ev.get("document") or {}
                if doc.get("status") == "tombstoned" or ev.get("chunk_text") == "(chunk removed)":
                    out.append(_issue("C8", "warn", "claim cites a source that has since been "
                                      "removed", claim_id=c.get("claim_id")))
                    continue
                if not match_quote(ev.get("quote", ""), ev.get("chunk_text", ""),
                                   fuzzy_threshold=fuzzy).ok:
                    out.append(_issue("C6", "error", "quoted span is not in the cited chunk",
                                      claim_id=c.get("claim_id"),
                                      quote=(ev.get("quote") or "")[:120]))
                if ev.get("nli_label") == "contradiction":
                    out.append(_issue("C7", "error", "a shipped claim's own evidence is "
                                      "NLI-contradicted", claim_id=c.get("claim_id")))
    return out


def check_matrix(conf: dict, min_queries: int = 2, min_chunks: int = 4) -> list[dict]:
    out = []
    matrix = conf.get("evidence_matrix") or []
    f = conf.get("funnel") or {}
    tally = Counter()
    required = list(f.get("required_dimensions") or [])
    for row in matrix:
        for fd in row.get("findings") or []:
            if not fd.get("claim_id"):
                out.append(_issue("M1", "error", "matrix finding with no gate-verified claim",
                                  doc_id=row.get("doc_id"), dimension=fd.get("dimension")))
        for dim, cell in (row.get("cells") or {}).items():
            state = cell.get("state")
            if state not in _CELL_STATES:
                out.append(_issue("M2", "error", f"unknown cell state {state!r}",
                                  doc_id=row.get("doc_id"), dimension=dim))
                continue
            if not required or dim in required:
                tally[state] += 1
            if state == "not_reported":
                cov = cell.get("coverage") or {}
                if (not row.get("full_text", True) or (cov.get("queries") or 0) < min_queries
                        or (cov.get("chunks") or 0) < min_chunks):
                    out.append(_issue(
                        "M2", "error", "'not reported' published without the evidence of "
                        "search it requires (full text, enough queries and passages)",
                        doc_id=row.get("doc_id"), dimension=dim, coverage=cov,
                        full_text=row.get("full_text")))
    if required and f.get("cells_total"):
        for state, key in zip(_CELL_STATES, ("cells_reported", "cells_not_reported",
                                             "cells_not_applicable", "cells_uncertain")):
            if f.get(key) is not None and tally[state] != f[key]:
                out.append(_issue("F4", "error", f"funnel says {f[key]} {state} cells; the "
                                  f"matrix rows hold {tally[state]}"))
    # Study independence. Two rows that are one study (preprint + published
    # version, or a re-ingest) double every count they appear in.
    rows = [(r.get("doc_id"), _norm_title(r.get("title", ""))) for r in matrix]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i][1], rows[j][1]
            if a and b and (a == b or _jaccard(a, b) >= 0.9):
                out.append(_issue("M3", "warn", "two matrix rows look like the same study; "
                                  "every study count they share is inflated",
                                  doc_ids=[rows[i][0], rows[j][0]]))
    return out


def check_derived(conf: dict) -> list[dict]:
    """D statements: reproducible, attributable, restrained, and every pooled
    value is a value a study in its row-set actually reported."""
    from app.agents.normalize import parse_quantity
    from app.agents.statements import derive_statements
    from app.agents.synthesis import synthesize
    out = []
    matrix = conf.get("evidence_matrix") or []
    stmts = conf.get("derived_statements") or []
    docs = {r.get("doc_id") for r in matrix}
    schema = conf.get("evidence_schema") or {}
    kinds = {d.get("name", ""): d.get("kind", "quantitative")
             for d in list(schema.get("required_dimensions") or [])
             + list(schema.get("optional_dimensions") or []) if d.get("name")}
    if matrix and stmts:
        again = [s["text"] for s in derive_statements(synthesize(matrix, kinds), matrix)]
        shipped = [s.get("text", "") for s in stmts]
        if again != shipped:
            missing = [t for t in shipped if t not in again]
            out.append(_issue(
                "D1", "error" if missing else "warn",
                "derived statements are not reproduced by recomputation from the "
                "persisted matrix" + ("" if missing else " (order/extra only)"),
                not_reproduced=missing[:5], recomputed_only=[t for t in again if t not in shipped][:5]))
    values_by_doc: dict[str, list[float]] = {}
    for r in matrix:
        for fd in r.get("findings") or []:
            q = parse_quantity(fd.get("value") or "")
            if q.ok:
                values_by_doc.setdefault(r.get("doc_id"), []).append(q.number)
    num = re.compile(r"-?\d+(?:\.\d+)?")
    for s in stmts:
        text = s.get("text", "")
        ids = s.get("doc_ids") or []
        if not ids or not set(ids) <= docs:
            out.append(_issue("D2", "error", "derived statement does not resolve to matrix rows",
                              text=text[:140]))
        low = " " + text.lower()
        for phrase in _D_BANNED:
            if phrase in low:
                out.append(_issue("D3", "error", f"derived statement says more than its counts "
                                  f"({phrase.strip()!r})", text=text[:140]))
        if s.get("kind") == "pooled":
            m = re.search(r"spans (\S+?)(?:\s\S+)? to (\S+?)[\s.(]|all reported (\S+?)[\s.]", text + " ")
            pool = [v for d in ids for v in values_by_doc.get(d, [])]
            for raw in [g for g in (m.groups() if m else ()) if g]:
                nm = num.search(raw)
                if nm and not any(abs(float(nm.group()) - v) <= max(1e-6, abs(v) * 5e-4)
                                  for v in pool):
                    out.append(_issue("D4", "error", "pooled value printed in a derived "
                                      "statement is not a value any study in its row-set "
                                      "reported", value=raw, text=text[:140]))
    return out


def check_references(payload: dict) -> list[dict]:
    out = []
    conf = payload.get("confidence") or {}
    refs = payload.get("references") or []
    cited = set()
    for s in payload.get("sections") or []:
        for c in s.get("claims") or []:
            for ev in c.get("evidence") or []:
                did = (ev.get("document") or {}).get("id")
                if did:
                    cited.add(did)
    scope = conf.get("scope") or {}
    since, until = scope.get("since_year") or 0, scope.get("until_year") or 0
    seen: dict[str, str] = {}
    for r in refs:
        did = r.get("document_id")
        if cited and did not in cited:
            out.append(_issue("R1", "warn", "reference list includes a document no claim in "
                              "THIS report cites (the list is project-wide)",
                              document_id=did, title=(r.get("title") or "")[:100]))
            continue
        missing = [k for k in ("year", "authors", "url") if not r.get(k)]
        if missing:
            out.append(_issue("R2", "warn", f"reference cannot be cited as-is: no {', '.join(missing)}",
                              document_id=did, title=(r.get("title") or "")[:100]))
        y = r.get("year") or 0
        if y and ((since and y < since) or (until and y > until)):
            out.append(_issue("R4", "error", f"cited study from {y} is outside the review's "
                              f"window {since or '…'}–{until or '…'}", document_id=did))
        key = _norm_title(r.get("title", ""))
        if key and key in seen:
            out.append(_issue("R3", "warn", "duplicate reference (same title)",
                              document_ids=[seen[key], did]))
        seen.setdefault(key, did)
    return out


def audit(payload: dict) -> dict:
    from app.core.config import get_settings
    st = get_settings()
    conf = payload.get("confidence") or {}
    issues = (check_funnel(conf) + check_sections(payload)
              + check_evidence(payload, st.quote_fuzzy_threshold)
              + check_matrix(conf, st.evidence_absence_min_queries, st.evidence_absence_min_chunks)
              + check_derived(conf) + check_references(payload))
    counts = Counter(i["severity"] for i in issues)
    n_claims = sum(len(s.get("claim_ids") or []) for s in payload.get("sections") or [])
    return {"report_id": payload.get("id"), "title": payload.get("title"),
            "checked": {"sections": len(payload.get("sections") or []), "claims": n_claims,
                        "matrix_rows": len(conf.get("evidence_matrix") or []),
                        "derived_statements": len(conf.get("derived_statements") or []),
                        "references": len(payload.get("references") or [])},
            "errors": counts.get("error", 0), "warnings": counts.get("warn", 0),
            "by_code": dict(Counter(i["code"] for i in issues)), "issues": issues}


async def _from_db(report_id: str) -> dict:
    from app.api.routes import _report_payload
    from app.db.models import Report
    from app.db.session import session_scope
    async with session_scope() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise SystemExit(f"no report {report_id}")
        return await _report_payload(session, report)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--json", help="a GET /api/report/{id} response body")
    g.add_argument("--report", help="report id, read from DATABASE_URL")
    ap.add_argument("--out")
    args = ap.parse_args()
    payload = (json.loads(Path(args.json).read_text("utf-8")) if args.json
               else asyncio.run(_from_db(args.report)))
    result = audit(payload)
    print(f"=== Integrity audit: {result['title']!r} ===")
    print(f"checked {result['checked']}")
    print(f"{result['errors']} error(s), {result['warnings']} warning(s)  {result['by_code']}")
    for i in result["issues"]:
        print(f"  [{i['severity'].upper():5}] {i['code']} {i['message']}")
        if i.get("evidence"):
            print(f"          {json.dumps(i['evidence'], default=str)[:220]}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=1, default=str), "utf-8")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
