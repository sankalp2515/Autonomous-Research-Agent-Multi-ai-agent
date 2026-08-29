"""Evidence-acquisition benchmark (Phase 14) — before vs after, measured.

WHY THIS EXISTS. "The report looks better" is not evidence. The claim this
rework has to defend is narrow and checkable: the evidence matrix was missing
cells whose evidence WAS IN THE CORPUS, and dimension-directed retrieval finds
them. That is a retrieval-recall claim, so it is measured with retrieval, on the
real corpus, with no LLM in the loop and no run-to-run randomness.

It deliberately does NOT reward a higher fill rate on its own. A fabricated or
context-free value is worse than an honestly-labeled hole, so the report also
carries the mislabel rate: cells the pipeline called "not reported" while the
paper demonstrably contains that evidence. That number must stay at zero — it is
the metric that catches "improving" the matrix by lowering the epistemic bar.

DEFINITIONS (deterministic, no model judgment)

  recoverable(study, dimension)
      the study has at least one chunk that mentions the dimension's vocabulary
      AND — for a quantitative dimension — carries a measurement-shaped number.
      This is a LOWER bound on what is really there: a table whose header sits in
      a neighbouring chunk will not count.

  retrieved_before / retrieved_after
      whether such a chunk appears in the passages the OLD path (one generic
      objective query, top-8, production code) or the NEW path (one search per
      dimension) hands the extractor. Extraction recall cannot exceed this, so
      it is the honest place to measure the fix.

USAGE
    python -m evals.evidence_bench --report <report_id>          # full compare
    python -m evals.evidence_bench --report <report_id> --json out.json

Runs against whatever DATABASE_URL points at. Dense retrieval is skipped when no
local embedding stack is present, which makes both arms lexical-only — a
conservative comparison that understates the new path (it loses its dense half
too), never the reverse.
"""

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select

from app.agents.schemas import ResearchEvidenceSchema
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Chunk, ClaimEvidence, Document, Report, Run
from app.db.session import session_scope
from app.retrieval.dimension import DimensionSpec, retrieve_by_dimension

# ── What counts as "the paper reports this" ──────────────────────────────
# This has to be strict, because it is the denominator of every claim the
# benchmark makes. A first cut that merely asked "does this chunk mention the
# dimension and contain a number?" called 57 of 62 empty cells recoverable and
# credited the OLD retrieval with 75% recall — both artefacts of matching a
# one-letter unit ('s') as a substring and of treating "1990s" as a measurement.
#
# The operational definition used here: ONE SENTENCE that names the dimension in
# the paper's own vocabulary AND carries a measurement with a unit. That
# under-counts (a table whose header sits in a neighbouring chunk will not
# qualify), so every "recoverable" number below is a LOWER bound on what the
# corpus really holds — the conservative direction for a claim of improvement.

# Units unambiguous enough to accept adjacent to their figure ("9.03s", "89%").
_UNIT_CLEAR = (r"%|ms\b|msec\b|sec\b|secs\b|seconds?\b|minutes?\b|hours?\b|"
               r"tokens?\b|usd\b|qps\b|gb\b|mb\b|kb\b|flops\b|f1\b|em\b|"
               r"points?\b|pp\b")
# Single-letter units are only a measurement when SPACED from the figure —
# otherwise "1990s" and "GPT4b" read as timings.
_UNIT_AMBIGUOUS = r"s\b|m\b|k\b|b\b|x\b|×"

_MEASUREMENT = re.compile(
    r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:" + _UNIT_CLEAR + r")"
    r"|(?<![\w.])\d[\d,]*(?:\.\d+)?\s+(?:" + _UNIT_AMBIGUOUS + r")"
    r"|\$\s?\d",
    re.IGNORECASE,
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

# Fallback vocabulary used ONLY when the run's generated schema has no entry for
# a dimension label the old report used. Kept generic on purpose: the benchmark
# must not smuggle in hand-tuned synonyms for the very cells it is scoring, or it
# would be measuring the fixture instead of the system. Terms shorter than three
# characters are excluded — they are units, and units are tested separately.
_GENERIC_TERMS = {
    "latency": ["latency", "response time", "query time", "runtime", "wall clock",
                "seconds", "milliseconds", "throughput"],
    "time": ["time", "runtime", "duration", "seconds"],
    "index": ["index", "indexing", "construction", "build time", "preprocessing"],
    "token": ["token", "tokens", "token cost", "prompt length"],
    "cost": ["cost", "usd", "dollars", "compute", "budget"],
    "accuracy": ["accuracy", "f1", "exact match", "precision", "recall", "score"],
    "memory": ["memory", "footprint", "storage"],
    "limitation": ["limitation", "limitations", "future work", "drawback",
                   "shortcoming", "weakness", "challenge"],
}


@dataclass
class CellResult:
    study: str
    doc_id: str
    dimension: str
    filled_before: bool
    recoverable: bool
    retrieved_before: bool
    retrieved_after: bool
    labeled_state: str = ""      # from the new pipeline, when present
    evidence_chunks: int = 0


@dataclass
class BenchReport:
    report_id: str
    query: str
    schema_used: bool = False
    reranked: bool = False
    studies: int = 0
    dimensions: list[str] = field(default_factory=list)
    cells: list[CellResult] = field(default_factory=list)
    funnel: dict = field(default_factory=dict)
    run: dict = field(default_factory=dict)
    citation: dict = field(default_factory=dict)


def _spec_for(label: str, schema: ResearchEvidenceSchema | None) -> DimensionSpec:
    """Map a report's dimension label onto the run's schema entry, else a bare
    spec built from the label itself (the conservative choice: fewer synonyms
    makes the NEW arm harder to satisfy, not easier)."""
    if schema:
        for d in [*schema.required_dimensions, *schema.optional_dimensions]:
            if d.name == label.lower() or d.name in label.lower() or label.lower() in d.name:
                return DimensionSpec(name=label, kind=d.kind, description=d.description,
                                     synonyms=list(d.synonyms), metrics=list(d.metrics),
                                     location_hints=list(d.location_hints))
    syn: list[str] = []
    low = label.lower()
    for key, extra in _GENERIC_TERMS.items():
        if key in low:
            syn.extend(extra)
    kind = "qualitative" if any(
        w in low for w in ("limitation", "challenge", "risk", "design")) else "quantitative"
    return DimensionSpec(name=label, kind=kind, synonyms=sorted(set(syn)),
                         metrics=[], location_hints=[])


def _terms(spec: DimensionSpec) -> list[str]:
    """Dimension vocabulary worth matching on. Units are excluded: 's' matching
    as a substring is what made the first version of this benchmark useless."""
    out = {spec.name.lower()}
    out.update(s.lower() for s in spec.synonyms if len(s) >= 3)
    # A multi-word axis is also findable by its head noun ("indexing latency"
    # -> "indexing", "latency"), which is how papers actually phrase it.
    for word in spec.name.lower().split():
        if len(word) >= 4:
            out.add(word)
    return sorted(t for t in out if t)


def _mentions(terms: list[str], text: str) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low)
               for t in terms)


def _is_evidence(spec: DimensionSpec, text: str) -> bool:
    """Does a SINGLE SENTENCE here both name the axis and state a measurement?

    Sentence-level co-occurrence is the point: a paper whose introduction says
    "latency matters" and whose results table says "89.2" has not reported a
    latency measurement, and counting it as one would inflate the very number
    this benchmark exists to keep honest.
    """
    terms = _terms(spec)
    for sentence in _SENTENCE.split(text or ""):
        if not _mentions(terms, sentence):
            continue
        if spec.kind != "quantitative" or _MEASUREMENT.search(sentence):
            return True
    return False


async def _old_path_chunks(session, project_id: str, doc_id: str, objective: str):
    """The production code path as it stood: one generic query, top-8, per doc."""
    from app.retrieval.hybrid import retrieve
    settings = get_settings()
    return await retrieve(
        session, project_id, objective, document_ids=[doc_id],
        top_k=settings.evidence_chunks_per_paper,
        max_per_doc=settings.evidence_chunks_per_paper,
        use_rerank=False,
    )


async def _derive_schema(query: str, objective: str) -> ResearchEvidenceSchema | None:
    """Generate the run's evidence schema exactly as the pipeline does.

    Needs an LLM key; without one the benchmark still runs, using the generic
    label-derived vocabulary above (and reporting that it did so).
    """
    from app.llm.router import complete_json
    from app.agents.nodes import _SCHEMA_SYSTEM
    try:
        res = await complete_json(
            "structure",
            "Research question: " + query + "\nObjective: " + objective + "\n\n"
            "Design the evidence schema this question requires.",
            ResearchEvidenceSchema, system=_SCHEMA_SYSTEM, temperature=0.0,
        )
        return res.normalized()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! schema generation unavailable ({str(exc)[:80]}); "
              "using label-derived vocabulary", file=sys.stderr)
        return None


async def bench(report_id: str, use_rerank: bool = False) -> BenchReport:
    async with session_scope() as session:
        report = await session.get(Report, report_id)
        if report is None:
            raise SystemExit(f"no report {report_id}")
        run = await session.get(Run, report.run_id)
        project_id = report.project_id
        matrix = (report.confidence or {}).get("evidence_matrix") or []
        funnel = (report.confidence or {}).get("funnel") or {}
        query = run.query if run else report.title

        out = BenchReport(report_id=report_id, query=query,
                          studies=len(matrix), funnel=funnel)
        if run:
            out.run = {"llm_calls": (run.budgets_spent or {}).get("llm_calls"),
                       "seconds": (run.budgets_spent or {}).get("seconds"),
                       "tokens_in": (run.budgets_spent or {}).get("tokens_in"),
                       "tokens_out": (run.budgets_spent or {}).get("tokens_out"),
                       "status": run.status}

        # The grid exactly as the report rendered it: dimensions ordered by how
        # many studies report each, top 6 — the same rule as the UI, so the
        # denominators here are the ones the reader actually saw.
        counts = Counter()
        for row in matrix:
            for d in {f["dimension"] for f in row.get("findings", [])}:
                counts[d] += 1
        dims = [d for d, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:6]
        out.dimensions = dims
        if not dims:
            return out

        objective = ((report.confidence or {}).get("plan") or {}).get("objective") or query
        schema = await _derive_schema(query, objective)
        specs = {d: _spec_for(d, schema) for d in dims}
        out.schema_used = schema is not None
        out.reranked = use_rerank

        for row in matrix:
            doc_id = row["doc_id"]
            doc = await session.get(Document, doc_id)
            chunks = (await session.execute(
                select(Chunk).where(Chunk.document_id == doc_id)
            )).scalars().all()
            filled = {f["dimension"] for f in row.get("findings", [])}
            cells_meta = row.get("cells") or {}

            before = await _old_path_chunks(session, project_id, doc_id, objective)
            before_ids = {c.chunk_id for c in before}
            after, _cov = await retrieve_by_dimension(
                session, project_id, doc_id,
                [specs[d] for d in dims],
                entities=list((schema.entities if schema else [])),
                objective=objective, use_rerank=use_rerank,
            )
            after_ids = {c.chunk_id for c in after}

            for d in dims:
                spec = specs[d]
                evidence_ids = {c.id for c in chunks if _is_evidence(spec, c.text)}
                out.cells.append(CellResult(
                    study=(doc.title if doc else row.get("title", ""))[:60],
                    doc_id=doc_id, dimension=d,
                    filled_before=d in filled,
                    recoverable=bool(evidence_ids),
                    retrieved_before=bool(evidence_ids & before_ids),
                    retrieved_after=bool(evidence_ids & after_ids),
                    labeled_state=(cells_meta.get(d) or {}).get("state", ""),
                    evidence_chunks=len(evidence_ids),
                ))

        # Citation concentration: how much of the report rests on one paper.
        claim_ids = [cid for s in (report.sections or []) for cid in s.get("claim_ids", [])]
        if claim_ids:
            rows = (await session.execute(
                select(Chunk.document_id)
                .join(ClaimEvidence, ClaimEvidence.chunk_id == Chunk.id)
                .where(ClaimEvidence.claim_id.in_(claim_ids))
            )).scalars().all()
            per_doc = Counter(rows)
            total = sum(per_doc.values()) or 1
            out.citation = {
                "claims": total,
                "documents_cited": len(per_doc),
                "top_document_share": round(max(per_doc.values()) / total, 3),
            }
        return out


def summarize(b: BenchReport) -> dict:
    cells = b.cells
    n = len(cells)
    filled = [c for c in cells if c.filled_before]
    empty = [c for c in cells if not c.filled_before]
    recoverable_missed = [c for c in empty if c.recoverable]
    genuinely_absent = [c for c in empty if not c.recoverable]

    # The headline: of the cells that were empty despite the evidence existing,
    # how many does each retrieval arm actually put in front of the extractor?
    before_hit = [c for c in recoverable_missed if c.retrieved_before]
    after_hit = [c for c in recoverable_missed if c.retrieved_after]

    # The guard rail: a cell the pipeline declared "not reported" while the
    # paper demonstrably carries that evidence. Must be 0.
    mislabeled = [c for c in cells
                  if c.labeled_state == "not_reported" and c.recoverable]
    states = Counter(c.labeled_state for c in cells if c.labeled_state)

    pct = lambda a, b_: round(100.0 * a / b_, 1) if b_ else 0.0  # noqa: E731
    return {
        "report_id": b.report_id,
        "query": b.query[:120],
        "dimension_vocabulary": ("generated evidence schema" if b.schema_used
                                 else "generic label-derived fallback"),
        "reranked": b.reranked,
        "grid": {"studies": b.studies, "dimensions": b.dimensions, "cells": n},
        "fill": {
            "filled": len(filled), "fill_rate_pct": pct(len(filled), n),
            "empty": len(empty),
            "empty_but_recoverable": len(recoverable_missed),
            "empty_and_genuinely_absent": len(genuinely_absent),
            "recoverable_pct_of_all_cells": pct(len(recoverable_missed), n),
        },
        "retrieval_recall_on_missed_cells": {
            "population": len(recoverable_missed),
            "old_single_query_top8": len(before_hit),
            "old_recall_pct": pct(len(before_hit), len(recoverable_missed)),
            "new_dimension_directed": len(after_hit),
            "new_recall_pct": pct(len(after_hit), len(recoverable_missed)),
        },
        "labeling": {
            "states": dict(states),
            "mislabeled_not_reported": len(mislabeled),
            "mislabeled_examples": [f"{c.study} / {c.dimension}" for c in mislabeled[:5]],
        },
        "funnel": b.funnel,
        "run": b.run,
        "citation_concentration": b.citation,
    }



async def compare_matrices(baseline_report_id: str, new_matrix: list[dict],
                           schema_dict: dict | None = None) -> dict:
    """Symmetric, label-independent comparison of two extraction arms.

    WHY NOT COMPARE CELLS BY LABEL. The evidence schema names its axes from the
    QUESTION ("computational efficiency"); the baseline's labels emerged from
    whatever the extractor happened to write ("retrieval latency", "token
    usage", "indexing latency"). Those grids are not the same objects, so a
    fill-rate difference between them measures vocabulary, not evidence. An
    earlier version of this function scored the baseline by label and the new arm
    by content and produced a 22-point "regression" that was purely an artefact
    of that asymmetry.

    So both arms are scored by exactly one rule, on exactly one axis set: for
    each study and each axis, does that arm hold a verified finding whose TEXT
    answers the axis — judged by the same detector that decides whether the
    paper contained the evidence at all? Conservative for both (a finding must
    name the axis and, if quantitative, carry a measurement), and symmetric,
    which is what makes the delta mean something.
    """
    async with session_scope() as session:
        report = await session.get(Report, baseline_report_id)
        if report is None:
            raise SystemExit(f"no report {baseline_report_id}")
        run = await session.get(Run, report.run_id)
        base_matrix = (report.confidence or {}).get("evidence_matrix") or []
        query = run.query if run else report.title
        objective = ((report.confidence or {}).get("plan") or {}).get("objective") or query

        schema = None
        if schema_dict:
            try:
                schema = ResearchEvidenceSchema.model_validate(schema_dict)
            except Exception:  # noqa: BLE001
                schema = None
        if schema is None:
            schema = await _derive_schema(query, objective)

        # The axis set: the baseline's own dimensions (what the reader saw)
        # UNION the schema's required axes (what the new arm was audited on).
        # Union rather than either alone, so neither arm is scored only on the
        # vocabulary that happens to favour it.
        counts = Counter()
        for row in base_matrix:
            for d in {f["dimension"] for f in row.get("findings", [])}:
                counts[d] += 1
        axes = [d for d, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:6]
        for d in (schema.required_dimensions if schema else []):
            if d.name not in axes:
                axes.append(d.name)
        specs = {a: _spec_for(a, schema) for a in axes}

        def answers(findings: list[dict], spec: DimensionSpec) -> bool:
            return any(_is_evidence(spec, " ".join(
                (f.get("text", ""), f.get("value", ""), f.get("metric", ""))))
                for f in findings)

        by_doc = {r["doc_id"]: r for r in new_matrix}
        rows = []
        for base_row in base_matrix:
            doc_id = base_row["doc_id"]
            doc = await session.get(Document, doc_id)
            chunks = (await session.execute(
                select(Chunk).where(Chunk.document_id == doc_id)
            )).scalars().all()
            new_row = by_doc.get(doc_id, {})
            for a in axes:
                spec = specs[a]
                rows.append(CellResult(
                    study=(doc.title if doc else base_row.get("title", ""))[:60],
                    doc_id=doc_id, dimension=a,
                    filled_before=answers(base_row.get("findings", []), spec),
                    recoverable=any(_is_evidence(spec, c.text) for c in chunks),
                    retrieved_before=False,
                    retrieved_after=answers(new_row.get("findings", []), spec),
                    evidence_chunks=sum(1 for c in chunks if _is_evidence(spec, c.text)),
                ))

        # The labeling audit runs on the NEW arm's OWN grid with the NEW arm's
        # OWN axis definitions. Judging a "not reported" verdict through some
        # other run's vocabulary would be exactly the category error above.
        label_rows = []
        if schema:
            for row in new_matrix:
                chunks = (await session.execute(
                    select(Chunk).where(Chunk.document_id == row["doc_id"])
                )).scalars().all()
                for d in schema.required_dimensions:
                    cell = (row.get("cells") or {}).get(d.name)
                    if not cell:
                        continue
                    spec = DimensionSpec(name=d.name, kind=d.kind,
                                         synonyms=list(d.synonyms),
                                         metrics=list(d.metrics))
                    label_rows.append((row.get("title", "")[:60], d.name,
                                       cell.get("state", ""),
                                       any(_is_evidence(spec, c.text) for c in chunks)))

        return {"axes": axes, "cells": rows, "labels": label_rows,
                "schema_used": schema is not None,
                "baseline_studies": len(base_matrix)}


def summarize_comparison(cmp: dict, cost: dict) -> dict:
    cells = cmp["cells"]
    n = len(cells)
    before = [c for c in cells if c.filled_before]
    after = [c for c in cells if c.retrieved_after]
    recoverable = [c for c in cells if c.recoverable]

    gained = [c for c in cells if c.retrieved_after and not c.filled_before]
    lost = [c for c in cells if c.filled_before and not c.retrieved_after]

    # Recall against the evidence the CORPUS actually contains — the only
    # denominator that is a property of the papers rather than of a run.
    rec_before = [c for c in recoverable if c.filled_before]
    rec_after = [c for c in recoverable if c.retrieved_after]

    states = Counter(st for _s, _d, st, _r in cmp["labels"])
    mislabeled = [(s, d) for s, d, st, rec in cmp["labels"]
                  if st == "not_reported" and rec]

    pct = lambda a, b: round(100.0 * a / b, 1) if b else 0.0  # noqa: E731
    return {
        "axes": cmp["axes"],
        "grid": {"studies": cmp["baseline_studies"], "axes": len(cmp["axes"]),
                 "cells": n,
                 "note": "both arms scored by the SAME content detector on the "
                         "SAME axis set (baseline labels ∪ schema required axes)"},
        "cells_answered": {
            "before": len(before), "before_pct": pct(len(before), n),
            "after": len(after), "after_pct": pct(len(after), n),
            "gained": len(gained), "lost": len(lost),
        },
        "recall_vs_corpus": {
            "cells_whose_evidence_is_in_the_corpus": len(recoverable),
            "before": len(rec_before), "before_pct": pct(len(rec_before), len(recoverable)),
            "after": len(rec_after), "after_pct": pct(len(rec_after), len(recoverable)),
        },
        "labeling_audit": {
            "scope": "new arm, its own required axes",
            "states": dict(states),
            "mislabeled_not_reported": len(mislabeled),
            "mislabeled_examples": [f"{s} / {d}" for s, d in mislabeled[:5]],
        },
        "cost": cost,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="report id to benchmark")
    ap.add_argument("--json", default="", help="write the full result here")
    ap.add_argument("--cells", action="store_true", help="print every cell")
    ap.add_argument("--matrix", default="",
                    help="score an extraction_ab replay json against --report's grid")
    ap.add_argument("--rerank", action="store_true",
                    help="enable the cross-encoder inside dimension retrieval "
                         "(matches the shipped default; slower)")
    args = ap.parse_args()

    configure_logging("WARNING", "console")

    if args.matrix:
        with open(args.matrix, encoding="utf-8") as fh:
            replay = json.load(fh)
        cmp = await compare_matrices(args.report, replay.get("matrix", []),
                                     schema_dict=replay.get("schema"))
        out = summarize_comparison(cmp, {
            "arm": replay.get("arm", ""),
            **{k: replay.get(k) for k in
               ("llm_calls", "wall_seconds", "drafted", "verified",
                "recovered_findings", "studies_extracted", "findings")}})
        print(json.dumps(out, indent=2))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"summary": out,
                           "cells": [vars(c) for c in cmp["cells"]]}, fh, indent=2)
        return 0

    b = await bench(args.report, use_rerank=args.rerank)
    s = summarize(b)
    print(json.dumps(s, indent=2))

    if args.cells:
        print("\nstudy | dimension | filled | recoverable | old | new | state")
        for c in sorted(b.cells, key=lambda c: (c.dimension, c.study)):
            print(f"{c.study[:46]:48s} {c.dimension[:20]:22s} "
                  f"{'Y' if c.filled_before else '.':2s} "
                  f"{'Y' if c.recoverable else '.':2s}({c.evidence_chunks:2d}) "
                  f"{'Y' if c.retrieved_before else '.':2s} "
                  f"{'Y' if c.retrieved_after else '.':2s} {c.labeled_state}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": s, "cells": [vars(c) for c in b.cells]}, fh, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
