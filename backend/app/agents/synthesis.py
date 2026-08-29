"""Cross-study synthesis, contradiction analysis, state of knowledge (P1 G/H/I).

WHAT THIS IS NOT. `app/services/analysis.py` already runs NLI over pairs of
verified claims and surfaces sentence-level tensions. That is a useful detector
and it stays — but it answers "do these two sentences contradict?", which is a
question about LANGUAGE. A literature review needs the question about EVIDENCE:
do studies measuring the same thing, the same way, on the same data, report
different outcomes — and if so, is that a real disagreement or an artefact of
them having tested different conditions? That distinction is the difference
between "the field disagrees about GraphRAG latency" and "one study measured on
an A100 and the other on a laptop", and no amount of sentence-pair NLI can tell
them apart.

So this module works on the NORMALIZED evidence matrix (app/agents/normalize.py)
and is deterministic end to end: same matrix in, same synthesis out. No LLM, no
sampling, no scores that cannot be traced to a count of studies.

THREE OUTPUTS

  G  cross-study synthesis  - per dimension: how many studies report it, how
                              many independently, what the values span, which
                              conditions were tested, how much of the corpus
                              contributes.
  H  contradiction analysis - disagreements found INSIDE a comparable bucket,
                              each classified as explained-by-conditions (the
                              studies differ in baseline/model/condition) or
                              unexplained (a genuine tension).
  I  state of knowledge     - an evidence-derived class per dimension, with the
                              counts that produced it stated in `basis`.

NLI IS NOT EVIDENCE STRENGTH. The gate's entailment score says a sentence is
faithful to its source. It says nothing about how many independent studies found
the effect, on how many datasets, or whether anyone disagrees. Those are
different axes and this module never mixes them: no NLI value is read here.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field

from app.agents.normalize import (
    EvidencePoint, canonical_entity, describe_context, entity_display,
    group_comparable, point_from_finding,
)

# ── Thresholds, and why each is where it is ──────────────────────────────
#
# All of these are counts of STUDIES, not model confidences, so they can be
# argued with. They are deliberately conservative: over-claiming consensus is
# the failure mode that matters in a system whose entire pitch is that it does
# not over-claim.

# Two measurements of the same thing that differ by more than this are treated
# as disagreeing. 10% relative is roughly the point at which a difference stops
# being attributable to seed/rounding in the benchmarks this corpus contains.
DISAGREEMENT_RELATIVE = 0.10
# Percentage-point axes need an absolute floor too: 2% vs 3% is a 50% relative
# gap but a 1-point difference nobody would call a contradiction.
DISAGREEMENT_ABSOLUTE_PP = 2.0

# Study counts behind each state-of-knowledge class.
STRONG_MIN_STUDIES = 5        # a claim the report may state plainly
MODERATE_MIN_STUDIES = 3      # a claim the report should qualify
EMERGING_MIN_STUDIES = 2      # a direction, not a finding
# Below EMERGING: one study is a datapoint; zero is silence.

STATE_STRONG = "strongly_supported"
STATE_MODERATE = "moderately_supported"
STATE_EMERGING = "emerging"
STATE_CONTESTED = "contested"
STATE_INSUFFICIENT = "insufficient_evidence"
STATE_UNKNOWN = "unknown"


@dataclass
class Contradiction:
    """Two studies reporting different outcomes for the SAME measurement."""
    dimension: str
    metric: str
    dataset: str
    task: str
    unit: str
    a_study: str
    a_value: str
    a_claim_id: str
    a_context: str
    b_study: str
    b_value: str
    b_claim_id: str
    b_context: str
    relative_gap: float
    # The heart of H: WHY they might differ, before anyone calls it a dispute.
    moderators: list[str] = field(default_factory=list)
    explained: bool = False

    @property
    def summary(self) -> str:
        if self.explained:
            return ("these studies measured under different conditions ("
                    + ", ".join(self.moderators) + "), so the difference is not "
                    "necessarily a disagreement")
        return ("these studies report different outcomes for the same "
                "measurement with no recorded difference in conditions")


@dataclass
class DimensionSynthesis:
    dimension: str
    studies: int = 0                 # studies reporting this axis at all
    findings: int = 0
    quantified: int = 0              # findings whose value parsed to a number
    comparable_sets: int = 0         # buckets of genuinely comparable numbers
    largest_comparable_set: int = 0
    datasets: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    baselines: list[str] = field(default_factory=list)
    value_spans: list[dict] = field(default_factory=list)
    # S2 — within-study paired comparisons, aggregated across studies.
    directions: list[dict] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    unexplained_contradictions: int = 0
    corpus_coverage: float = 0.0     # share of extracted studies reporting it
    # 'quantitative' | 'qualitative', from the run's evidence schema. Carried so
    # gap derivation can tell "nobody measured this comparably" (a real hole in
    # a measured axis) from "this axis was never a measurement" (not a hole).
    kind: str = "quantitative"
    state: str = STATE_UNKNOWN
    basis: str = ""


def _display(bucket: list) -> tuple[str, str, str]:
    """How to PRINT a bucket's context: metric, dataset, task.

    `comparable_key` lowercases and canonicalises so that "HotpotQA" and
    "hotpotqa" match — correct for grouping, wrong for display. Printing the key
    put "hotpotqa" in front of the reader, mangling the name the paper actually
    used. The paper's own casing is preserved on the point, so display reads
    from there. Picked off the lowest doc_id so the choice is deterministic.
    """
    first = min(bucket, key=lambda p: (p.doc_id, p.claim_id))
    return first.metric, first.dataset, first.task


def _median(ordered: list[float]) -> float:
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _paired_directions(dimension: str, key: tuple, bucket: list) -> list[dict]:
    """Which system scored higher, counted WITHIN each study (S2).

    Only pairs a study measured ITSELF are used. Two numbers from two papers
    that merely share a benchmark name differ in a dozen unrecorded ways; two
    numbers from one paper's own table differ in the thing the paper varied.
    That is the difference between a direction and a coincidence.

    Deliberately NOT reported here: which system is *better*. Higher is better
    for F1 and worse for latency, and nothing in the matrix says which — that
    judgement is an I sentence. These rows carry only "scored higher".
    """
    _metric, _dataset, _task = _display(bucket)
    by_study: dict[str, list] = {}
    for p in bucket:
        # A delta and a level are not the same kind of number; pairing them
        # would compare an improvement against an absolute score.
        #
        # Identity goes through `_entity_of`, not the raw string: pairing on raw
        # text would treat "GraphRAG" and "Graph-RAG" as rivals, and — far worse
        # — would accept "ours" and "baseline" as system names. Those are
        # RELATIONAL labels that mean a different system in every paper, so a
        # tally across studies would pool unrelated results into one verdict.
        if p.quantity.ok and not p.quantity.signed and _entity_of(p):
            by_study.setdefault(p.doc_id, []).append(p)

    display_names: dict[str, list[str]] = {}
    tally: dict[tuple[str, str], dict] = {}
    for doc_id, points in by_study.items():
        # One study may report the same system twice (e.g. two runs); an
        # ambiguous within-study value cannot yield a direction.
        best: dict[str, list[float]] = {}
        for p in points:
            key_e = _entity_of(p)
            best.setdefault(key_e, []).append(p.quantity.number)
            display_names.setdefault(key_e, []).append(p.model)
        systems = {m: v[0] for m, v in best.items() if len(v) == 1}
        names = sorted(systems)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if systems[a] == systems[b]:
                    continue        # a tie is not a direction
                row = tally.setdefault((a, b), {
                    "dimension": dimension, "metric": _metric,
                    "dataset": _dataset, "task": _task,
                    "unit": key[4], "system_a": a, "system_b": b,
                    "a_higher": 0, "b_higher": 0, "doc_ids": [],
                })
                if systems[a] > systems[b]:
                    row["a_higher"] += 1
                else:
                    row["b_higher"] += 1
                row["doc_ids"].append(doc_id)

    out = []
    for row in tally.values():
        row["studies"] = row["a_higher"] + row["b_higher"]
        row["doc_ids"] = sorted(set(row["doc_ids"]))
        # The tally is keyed on the canonical form; the reader sees the papers'
        # own spelling. Keys are kept so the pair can be matched to a comparison
        # table row without re-deriving identity.
        row["key_a"], row["key_b"] = row["system_a"], row["system_b"]
        row["system_a"] = entity_display(display_names.get(row["key_a"], []))
        row["system_b"] = entity_display(display_names.get(row["key_b"], []))
        # One study is an observation, not a direction. Two is the floor at
        # which "of the N studies" is a count rather than a restatement.
        if row["studies"] >= 2:
            out.append(row)
    return sorted(out, key=lambda r: (-r["studies"], r["system_a"], r["system_b"]))


def _relative_gap(a: float, b: float) -> float:
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def _disagree(a: EvidencePoint, b: EvidencePoint) -> bool:
    """Do these two comparable measurements actually differ enough to matter?"""
    x, y = a.quantity.number, b.quantity.number
    if x is None or y is None:
        return False
    # A level and a DELTA are not the same kind of number; comparing "89.2%"
    # with "+31.79%" as if both were scores is a category error, not a finding.
    if a.quantity.signed != b.quantity.signed:
        return False
    if a.quantity.unit in ("%", "pp") and abs(x - y) < DISAGREEMENT_ABSOLUTE_PP:
        return False
    return _relative_gap(x, y) > DISAGREEMENT_RELATIVE


def _moderators(a: EvidencePoint, b: EvidencePoint) -> list[str]:
    """Recorded differences that could explain a gap without anyone being wrong.

    Only fields BOTH studies actually reported are compared. An empty field
    means we don't know, and an unknown is not evidence that the conditions
    matched — treating it as one would let us dismiss a real disagreement as a
    condition difference, which is the more damaging of the two errors.
    """
    out = []
    for label, x, y in (("baseline", a.baseline, b.baseline),
                        ("model", a.model, b.model),
                        ("condition", a.condition, b.condition)):
        if x and y and x.strip().lower() != y.strip().lower():
            out.append(f"{label}: {x} vs {y}")
    return out


def _classify(studies: int, unexplained: int, largest_set: int) -> tuple[str, str]:
    """Evidence-derived state, with the counts that produced it.

    Deliberately NOT a score. A number between 0 and 1 invites the reader to
    treat 0.72 as meaningful when the only real information is "four studies
    measured this and two of them disagree".
    """
    if studies == 0:
        return STATE_UNKNOWN, "no study in this corpus reports this dimension"
    if unexplained and studies >= EMERGING_MIN_STUDIES:
        return STATE_CONTESTED, (
            f"{studies} studies report this dimension, and {unexplained} pair(s) "
            "disagree on the same measurement with no difference in recorded "
            "conditions to explain it")
    if studies == 1:
        return STATE_INSUFFICIENT, (
            "only one study in this corpus reports this dimension, so nothing "
            "here can be cross-checked")
    if studies >= STRONG_MIN_STUDIES and largest_set >= 3:
        return STATE_STRONG, (
            f"{studies} independent studies report this dimension, {largest_set} "
            "of them on the same metric and dataset, with no unexplained "
            "disagreement between them")
    if studies >= MODERATE_MIN_STUDIES:
        # A basis string must not contradict itself. This used to read
        # "22 independent studies report this dimension, but at most 0 of them
        # measured it the same way, so the agreement is real but thinly
        # comparable" — describing an agreement that, by its own count, nobody
        # could have measured. When no two studies share a measurement there is
        # no agreement to characterise: the breadth is real and the
        # comparability is absent, and `research_gaps` separately raises this as
        # `no_comparable_evidence`. The two must tell the reader the same story.
        if largest_set < 2:
            return STATE_MODERATE, (
                f"{studies} independent studies report this dimension, but no "
                "two of them measured it the same way (same metric, dataset and "
                "task), so their numbers cannot be pooled or ranked — the "
                "breadth is real, the comparability is not")
        return STATE_MODERATE, (
            f"{studies} independent studies report this dimension"
            + (f", but only {largest_set} of them measured it the same way"
               if largest_set < 3 else "")
            + ", so the agreement is real but thinly comparable")
    return STATE_EMERGING, (
        f"{studies} studies report this dimension — enough to indicate a "
        "direction, not enough to call it established")


def _uniq(values) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return sorted(out)


# ── S3: the pivot from STUDY x dimension to SYSTEM x dimension ────────────
#
# The evidence matrix is indexed by study, because that is how evidence arrives:
# one paper, read on its own terms. Researchers do not reason that way. Asked to
# choose between GraphRAG and LightRAG they hold a system-indexed table in their
# head — for each system, what was measured, how often, and how it came out —
# and the study index makes them rebuild it by hand from twenty rows.
#
# THE TRAP THIS DESIGN AVOIDS. The obvious pivot is one grid: systems down the
# side, dimensions across the top, a number in each cell. That grid is a lie
# machine. Its columns invite exactly the comparison the rest of this module
# exists to forbid — "GraphRAG 91%, LightRAG 87%" reads as a ranking even when
# the numbers are F1 on HotpotQA and Recall@10 on MuSiQue, and no gate catches
# it because both numbers are real, quoted and correctly attributed.
#
# So the unit is not the grid but the MEASUREMENT CONTEXT. One table per
# (dimension, metric, dataset, task, unit, level-or-delta) — inside which every
# number is comparable by construction, because that tuple is precisely the
# definition of comparable this module already uses. A corpus that supports no
# such table produces none, which is the honest outcome and the one a fill-rate
# metric would punish.


def _entity_of(p: EvidencePoint) -> str:
    """The system a number belongs to, or "" when it cannot be attributed.

    Also rejects a model field that merely echoes the dataset or task: an
    extractor that wrote "HotpotQA" into `model` has told us nothing about which
    system was measured, and a row labelled with a benchmark name is worse than
    a row we declined to build.
    """
    key = canonical_entity(p.model)
    if not key:
        return ""
    if key in (canonical_entity(p.dataset), canonical_entity(p.task)):
        return ""
    return key


def build_comparisons(points_by_dim: dict[str, list]) -> list[dict]:
    """One table per measurement context: systems as rows, all comparable.

    A table needs at least two systems — one system is a measurement, not a
    comparison, and belongs to `entity_coverage` instead.
    """
    tables: list[dict] = []
    for dimension, points in points_by_dim.items():
        buckets = group_comparable(points)
        for key, bucket in buckets.items():
            by_context: dict[bool, list] = {}
            for p in bucket:
                if p.quantity.ok and _entity_of(p):
                    by_context.setdefault(p.quantity.signed, []).append(p)
            for signed, ctx_points in sorted(by_context.items()):
                by_entity: dict[str, list] = {}
                for p in ctx_points:
                    by_entity.setdefault(_entity_of(p), []).append(p)
                if len(by_entity) < 2:
                    continue

                rows = []
                for entity, e_points in by_entity.items():
                    numbers = sorted(p.quantity.number for p in e_points)
                    docs = sorted({p.doc_id for p in e_points})
                    rows.append({
                        "system": entity_display([p.model for p in e_points]),
                        "key": entity,
                        # Every spelling folded into this row, so a wrong merge
                        # is visible to the reader rather than silent.
                        "aliases": _uniq(p.model for p in e_points),
                        "studies": len(docs),
                        "doc_ids": docs,
                        "claim_ids": sorted({p.claim_id for p in e_points if p.claim_id}),
                        "min": numbers[0], "max": numbers[-1],
                        "median": _median(numbers), "values": numbers,
                    })
                # Neutral ordering: most-evidenced first, then alphabetical.
                # Sorting by value would rank the systems, and which end of the
                # scale is good depends on the axis — that is an I judgement.
                rows.sort(key=lambda r: (-r["studies"], r["system"]))

                # IS THIS A COMPARISON OR A COLLAGE? A table whose systems each
                # come from a different paper juxtaposes numbers that share only
                # a benchmark name. One where studies measured several of these
                # systems themselves compares them under conditions those studies
                # controlled. Same table shape, very different strength — so the
                # count is carried rather than left for the reader to infer.
                per_doc: dict[str, set] = {}
                for p in ctx_points:
                    per_doc.setdefault(p.doc_id, set()).add(_entity_of(p))
                within = sum(1 for systems in per_doc.values() if len(systems) >= 2)

                metric, dataset, task = _display(ctx_points)
                tables.append({
                    "dimension": dimension, "metric": metric, "dataset": dataset,
                    "task": task, "unit": key[4], "signed": signed,
                    "systems": len(rows), "studies": len(per_doc),
                    "within_study": within,
                    "rows": rows,
                })
    # Strongest comparisons first, then a total order over every field the
    # table is keyed by — an ordering that fell through to dict iteration order
    # would make two runs of one question render tables in different places.
    tables.sort(key=lambda t: (-t["within_study"], -t["studies"], -t["systems"],
                               t["dimension"], t["metric"], t["dataset"],
                               t["task"], t["unit"], t["signed"]))
    return tables


def build_entity_coverage(points_by_dim: dict[str, list]) -> list[dict]:
    """Per system: what this corpus actually measured about it.

    The counterpart to the comparison tables. A system measured once on one axis
    cannot appear in any table, and its absence there should not read as absence
    from the corpus — this is where it is accounted for.
    """
    entities: dict[str, dict] = {}
    for dimension, points in points_by_dim.items():
        for p in points:
            entity = _entity_of(p)
            if not entity:
                continue
            rec = entities.setdefault(entity, {
                "key": entity, "_names": [], "_docs": set(), "dimensions": {},
            })
            rec["_names"].append(p.model)
            rec["_docs"].add(p.doc_id)
            dim = rec["dimensions"].setdefault(
                dimension, {"dimension": dimension, "findings": 0, "_docs": set(),
                            "quantified": 0})
            dim["findings"] += 1
            dim["_docs"].add(p.doc_id)
            if p.quantity.ok:
                dim["quantified"] += 1

    out = []
    for rec in entities.values():
        dims = []
        for dim in rec["dimensions"].values():
            dims.append({"dimension": dim["dimension"], "findings": dim["findings"],
                         "quantified": dim["quantified"],
                         "studies": len(dim["_docs"])})
        dims.sort(key=lambda d: (-d["studies"], d["dimension"]))
        out.append({
            "key": rec["key"],
            "system": entity_display(rec["_names"]),
            "aliases": _uniq(rec["_names"]),
            "studies": len(rec["_docs"]),
            "doc_ids": sorted(rec["_docs"]),
            "dimensions": dims,
        })
    out.sort(key=lambda e: (-e["studies"], -len(e["dimensions"]), e["system"]))
    return out


def synthesize(matrix: list[dict],
               dimension_kinds: dict[str, str] | None = None) -> dict:
    """Cross-study synthesis over the evidence matrix. Pure function.

    `dimension_kinds` maps a dimension name to 'quantitative' or 'qualitative'
    (from the run's evidence schema). It only affects which GAPS are reportable:
    "no two studies measured it the same way" is a statement about measurement,
    and applying it to an axis nobody was measuring — architectural complexity,
    stated limitations — turns the gaps section into five identical-sounding
    complaints and buries the real ones.
    """
    total_studies = len(matrix)
    points_by_dim: dict[str, list[EvidencePoint]] = {}
    for row in matrix:
        for finding in row.get("findings", []):
            p = point_from_finding(row["doc_id"], row.get("title", ""), finding)
            if p.dimension:
                points_by_dim.setdefault(p.dimension, []).append(p)

    out: list[DimensionSynthesis] = []
    for dimension, points in points_by_dim.items():
        docs = {p.doc_id for p in points}
        syn = DimensionSynthesis(
            dimension=dimension,
            studies=len(docs),
            findings=len(points),
            quantified=sum(1 for p in points if p.quantity.ok),
            datasets=_uniq(p.dataset for p in points),
            tasks=_uniq(p.task for p in points),
            models=_uniq(p.model for p in points),
            baselines=_uniq(p.baseline for p in points),
            corpus_coverage=round(len(docs) / total_studies, 3) if total_studies else 0.0,
            kind=(dimension_kinds or {}).get(dimension, "quantitative"),
        )

        buckets = group_comparable(points)
        syn.comparable_sets = len(buckets)
        for key, bucket in buckets.items():
            # A span is only meaningful across DIFFERENT studies; three numbers
            # from one paper are one study's opinion, not a range in the field.
            by_doc = {p.doc_id: p for p in bucket}
            syn.largest_comparable_set = max(syn.largest_comparable_set, len(by_doc))
            # POOL PER SYSTEM, NEVER ACROSS SYSTEMS.
            #
            # A comparable bucket keys on dimension/metric/dataset/task — enough
            # to say two numbers measure the same THING, not enough to say they
            # measure the same SUBJECT. Pooling a bucket wholesale produced
            # "3 studies measured accuracy on HotpotQA: 80.2% to 91%" from a
            # bucket holding both GraphRAG and Vector RAG results: a range that
            # describes no system, spanning a gap that IS the finding. That is
            # the same category error as pooling F1 with Recall@10, one level
            # down, and no gate would catch it because every number is real.
            # Grouped by (system, signed). A LEVEL and a DELTA are different
            # kinds of number: "89.2%" is a score and "+31.79%" is a change in
            # one, and `group_comparable` keys on unit — which they share — so
            # they land in the same bucket. Pooling them produced ranges like
            # "spans +31.79% to 89.2%", a span between two incommensurable
            # things. `_disagree` and `_paired_directions` already guard this;
            # the span builder did not.
            per_system: dict[tuple[str, bool], list] = {}
            for p in bucket:
                if p.quantity.ok:
                    per_system.setdefault(
                        ((p.model or "").strip(), p.quantity.signed), []).append(p)
            for (system, signed), sys_points in sorted(
                    per_system.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                s_by_doc = {p.doc_id: p for p in sys_points}
                s_numbers = [p.quantity.number for p in sys_points]
                if len(s_by_doc) < 2 or not s_numbers:
                    continue
                s_ordered = sorted(s_numbers)
                s_metric, s_dataset, s_task = _display(sys_points)
                syn.value_spans.append({
                    "metric": s_metric, "dataset": s_dataset, "task": s_task,
                    "unit": key[4], "system": system, "signed": signed,
                    "studies": len(s_by_doc),
                    "min": s_ordered[0], "max": s_ordered[-1],
                    "median": _median(s_ordered),
                    "values": s_ordered,
                    "doc_ids": sorted(s_by_doc),
                })

            # S2. WITHIN-STUDY PAIRED COMPARISONS. A study that measured two
            # systems on the same metric, dataset and task compared them under
            # conditions IT controlled — which is a far stronger basis for a
            # direction than ranking numbers across papers that share only a
            # benchmark name. Counting how many studies came out each way is
            # arithmetic; calling either result "better" would not be, so the
            # sentence these produce says "higher", never "better".
            syn.directions.extend(_paired_directions(dimension, key, bucket))
            # H: pairwise disagreement inside the bucket, across studies only.
            items = list(by_doc.values())
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if not _disagree(a, b):
                        continue
                    mods = _moderators(a, b)
                    syn.contradictions.append(Contradiction(
                        dimension=dimension, metric=key[1], dataset=key[2],
                        task=key[3], unit=key[4],
                        a_study=a.study, a_value=a.quantity.raw,
                        a_claim_id=a.claim_id, a_context=describe_context(a),
                        b_study=b.study, b_value=b.quantity.raw,
                        b_claim_id=b.claim_id, b_context=describe_context(b),
                        relative_gap=round(_relative_gap(
                            a.quantity.number, b.quantity.number), 3),
                        moderators=mods, explained=bool(mods),
                    ))
        syn.unexplained_contradictions = sum(
            1 for c in syn.contradictions if not c.explained)
        syn.state, syn.basis = _classify(
            syn.studies, syn.unexplained_contradictions, syn.largest_comparable_set)
        out.append(syn)

    # Most-measured axes first: that ordering IS the coverage story.
    out.sort(key=lambda s: (-s.studies, s.dimension))
    states = Counter(s.state for s in out)
    result = {
        "studies_total": total_studies,
        "dimensions": [asdict(s) for s in out],
        "state_counts": dict(states),
        "contradictions_total": sum(len(s.contradictions) for s in out),
        "contradictions_unexplained": sum(s.unexplained_contradictions for s in out),
        # S3 — the SYSTEM-indexed view. `comparisons` is one table per
        # measurement context (everything inside one is comparable by
        # construction); `entity_coverage` accounts for every system, including
        # those with too little evidence to appear in any table.
        "comparisons": build_comparisons(points_by_dim),
        "entity_coverage": build_entity_coverage(points_by_dim),
        # Explicit, because it is the single most likely misreading of this
        # block by anyone reading the JSON later.
        "note": ("Evidence strength here is derived from study counts and "
                 "cross-study comparability, never from NLI entailment scores — "
                 "entailment measures a sentence's faithfulness to its source, "
                 "not how well established the finding is."),
    }
    # P2-J: gaps are read OFF the assembled synthesis, so a gap can never
    # disagree with the numbers printed beside it.
    result["gaps"] = research_gaps(result)
    return result


# ── P2-J: research gaps, derived from the matrix ─────────────────────────
#
# "More research is needed" is the sentence every literature review ends on and
# the one that carries no information. A gap is only worth printing if it names
# WHAT is missing and shows the count that makes it missing: 14 studies measured
# accuracy, 1 measured production cost — therefore cost is under-studied in this
# corpus. That sentence is checkable; the generic one is not.
#
# Every gap below is computed from study counts already in the synthesis, so it
# inherits their honesty: they describe THIS CORPUS, not the field. A gap here
# means "the papers this run retrieved do not establish X", which is exactly what
# a reader can act on when deciding whether to trust the review or go deeper.

# An axis reported by this share or less of the corpus, while some other axis is
# well covered, is under-measured RELATIVE to what the field evidently can do.
UNDER_MEASURED_SHARE = 0.34
WELL_COVERED_SHARE = 0.60

GAP_UNDER_MEASURED = "under_measured"
GAP_SINGLE_STUDY = "single_study"
GAP_NOT_COMPARABLE = "no_comparable_evidence"
GAP_CONTESTED = "contested"


@dataclass
class ResearchGap:
    kind: str
    dimension: str
    studies: int
    corpus_studies: int
    # The counts that produce the gap. This is the field that makes a gap a
    # finding rather than a platitude, so it is never optional.
    basis: str
    severity: str = "medium"


def research_gaps(result: dict) -> list[dict]:
    """Turn a synthesis result into named, counted gaps."""
    dims = result.get("dimensions", [])
    total = result.get("studies_total", 0)
    if not dims or not total:
        return []

    covered = [d for d in dims if d["corpus_coverage"] >= WELL_COVERED_SHARE]
    gaps: list[ResearchGap] = []

    for d in dims:
        name, n = d["dimension"], d["studies"]

        if d["unexplained_contradictions"]:
            gaps.append(ResearchGap(
                kind=GAP_CONTESTED, dimension=name, studies=n, corpus_studies=total,
                severity="high",
                basis=(f"{n} of {total} studies report {name}, and "
                       f"{d['unexplained_contradictions']} pair(s) disagree on the "
                       "same measurement with no difference in recorded conditions "
                       "to explain it — this axis needs a controlled comparison, "
                       "not another datapoint")))
            continue

        if n == 1:
            gaps.append(ResearchGap(
                kind=GAP_SINGLE_STUDY, dimension=name, studies=n, corpus_studies=total,
                severity="high",
                basis=(f"exactly one of {total} studies reports {name}, so nothing "
                       "in this corpus can corroborate or contradict it")))
            continue

        if covered and d["corpus_coverage"] <= UNDER_MEASURED_SHARE:
            leader = max(covered, key=lambda x: x["studies"])
            gaps.append(ResearchGap(
                kind=GAP_UNDER_MEASURED, dimension=name, studies=n, corpus_studies=total,
                severity="high" if n <= 2 else "medium",
                basis=(f"{leader['studies']} of {total} studies evaluate "
                       f"{leader['dimension']} but only {n} evaluate {name} — "
                       "the field measures what is easy to measure here")))
            continue

        # Measured by many, comparably by none: the subtler gap, and the one a
        # fill-rate metric hides completely. The column looks full; the evidence
        # cannot actually be pooled.
        # Only meaningful where a NUMBER was expected. A qualitative axis has
        # no shared benchmark to be missing.
        if (n >= 3 and d["largest_comparable_set"] <= 1
                and d.get("kind", "quantitative") != "qualitative"
                and d.get("quantified", 0) >= 2):
            gaps.append(ResearchGap(
                kind=GAP_NOT_COMPARABLE, dimension=name, studies=n, corpus_studies=total,
                severity="medium",
                basis=(f"{n} studies report {name}, but no two measured it the same "
                       "way (same metric, dataset and task), so the numbers cannot "
                       "be pooled or ranked — a shared benchmark is missing, not "
                       "more papers")))

    order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: (order.get(g.severity, 3), -g.corpus_studies, g.dimension))
    return [asdict(g) for g in gaps]


# ── P2-L: study characteristics ──────────────────────────────────────────
# What KIND of evidence this corpus is, before any claim is read from it. A
# reader judging a review wants to know the shape of the sample: how recent, how
# concentrated on which systems and benchmarks, and how much of it was read from
# full text rather than an abstract. All deterministic, all from the matrix.

def study_characteristics(matrix: list[dict], full_text_count: int | None = None,
                          ingested_count: int | None = None) -> dict:
    years = [r.get("year") for r in matrix if r.get("year")]
    frameworks, datasets, baselines = Counter(), Counter(), Counter()
    models = Counter()
    for row in matrix:
        for f in row.get("frameworks", []):
            frameworks[f.strip()] += 1
        for d in row.get("datasets", []):
            datasets[d.strip()] += 1
        for b in row.get("baselines", []):
            baselines[b.strip()] += 1
        for finding in row.get("findings", []):
            model = ((finding.get("context") or {}).get("model") or "").strip()
            if model:
                models[model] += 1

    def _top(counter: Counter, n: int = 10) -> list[dict]:
        return [{"name": k, "studies": v} for k, v in counter.most_common(n) if k]

    span = {"min": min(years), "max": max(years)} if years else None
    return {
        "studies": len(matrix),
        "year_span": span,
        "years": sorted(Counter(years).items()) if years else [],
        "full_text": full_text_count,
        # The denominator for full_text is papers INGESTED, not studies
        # extracted — a paper can be ingested from a PDF and still yield no
        # verified finding. Rendering "26/19" (as a live report did) is the kind
        # of impossible number that costs a reader more trust than the fact was
        # worth.
        "ingested": ingested_count,
        "frameworks": _top(frameworks),
        "datasets": _top(datasets),
        "baselines": _top(baselines, 8),
        "models": _top(models, 8),
        # Concentration: if one system dominates the corpus, every conclusion is
        # really a conclusion about that system.
        "framework_concentration": (
            round(frameworks.most_common(1)[0][1] / len(matrix), 3)
            if frameworks and matrix else 0.0),
    }
