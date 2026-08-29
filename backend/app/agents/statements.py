"""Typed statements — the report's sentences, each with the gate that fits it.

WHY THIS MODULE EXISTS. G1 used to require that EVERY sentence trace to a source
span. That is the right gate for a claim about the world and the wrong gate for
everything else, and because it was the only gate, the contract handled the rest
by banning it. The cost was concrete: `synthesis.py` computes facts about the
BODY of evidence — how many studies measured an axis, how many measured it the
same way, which pairs disagree — that no single paper states and no quote can
ground. They are not ungrounded; they are grounded in arithmetic over
gate-verified rows. Having nowhere to put them, the report exiled them into an
apparatus table, so its best material read as furniture.

Four sentence types, four gates:

    E  evidential   quote exact-match + NLI     -> one chunk_id + a citation
    D  derived      reproducible by recomputation -> the row-set it came from
    I  interpretive NLI against REPORT statements -> statement ids  (NOT SHIPPED)
    S  structural   asserts nothing              -> nothing

This module owns **D**. Every sentence here is produced by a template over
numbers `synthesis.py` already computed, with NO LLM anywhere in the path. That
is what makes the gate meaningful: a D sentence is falsifiable by re-running the
function, which is a harder guarantee than entailment. It also means the text
cannot drift from the numbers beside it — the sentence IS the numbers.

WHAT A D SENTENCE MAY SAY. Only what the counts support, and only about THIS
CORPUS. It may say "no two of the 12 studies measured this the same way"; it may
not say "the field lacks a shared benchmark". The first is arithmetic, the
second is an inference about the world — that is an I sentence, and I is not
shipped.

Every D statement carries `doc_ids`: the studies its arithmetic ran over, so the
reader can click through to exactly the rows that produced it. A D statement
with no provenance is not publishable and `derive_statements` will not emit one.
"""

from app.agents.synthesis import (
    STATE_CONTESTED,
    STATE_INSUFFICIENT,
    STATE_MODERATE,
    STATE_STRONG,
)

TYPE_EVIDENTIAL = "E"
TYPE_DERIVED = "D"
TYPE_STRUCTURAL = "S"
TYPE_INTERPRETIVE = "I"      # designed, gated, deliberately not emitted yet


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _docs_reporting(matrix: list[dict], dimension: str) -> list[str]:
    """Which studies actually contributed a finding on this axis.

    This is the D statement's provenance AND its precondition: a sentence
    counting studies must be able to name them.
    """
    out = []
    for row in matrix:
        doc_id = row.get("doc_id")
        if not doc_id:
            continue
        for finding in row.get("findings", []) or []:
            if (finding.get("dimension") or "").strip().lower() == dimension.strip().lower():
                out.append(doc_id)
                break
    return out


def _statement(text: str, dimension: str, doc_ids: list[str], basis: str,
               kind: str) -> dict:
    return {
        "type": TYPE_DERIVED,
        "kind": kind,
        "text": text,
        "dimension": dimension,
        # The row-set this was computed from — a D statement's answer to "cite
        # your source". It resolves to matrix rows, never to a single paper,
        # because no single paper says it.
        "doc_ids": doc_ids,
        "basis": basis,
    }


def _fmt(number: float) -> str:
    """Render a measurement without inventing precision it did not have."""
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.4g}"


def _qualified(span: dict) -> str:
    """The context that makes a pooled number mean anything.

    Never omitted. A span printed without its metric/dataset/task is exactly the
    false corroboration `normalize.py` exists to prevent — two studies reporting
    "89.2" are not agreeing when one is F1 on HotpotQA and the other Recall@10
    on MuSiQue.
    """
    bits = [b for b in (span.get("metric"), span.get("dataset"), span.get("task"))
            if (b or "").strip()]
    return " · ".join(bits)


def _pooled_statements(dim: dict, dimension: str) -> list[dict]:
    """S1 — the pooled result, as a sentence.

    `synthesize` has always computed these spans and nothing ever rendered them:
    the single number a researcher opened the report for was calculated,
    persisted, and thrown away. It is a D sentence by every rule — arithmetic
    over gate-verified rows, no LLM, provenance is the row-set.
    """
    out = []
    for span in dim.get("value_spans") or []:
        doc_ids = list(span.get("doc_ids") or [])
        studies = int(span.get("studies") or 0)
        if not doc_ids or studies < 2:
            continue
        unit = (span.get("unit") or "").strip()
        lo, hi = span.get("min"), span.get("max")
        if lo is None or hi is None:
            continue
        u = f" {unit}" if unit and unit not in ("%", "pp") else (unit or "")
        where = _qualified(span)
        # A span is pooled PER SYSTEM. Naming the system is not decoration: a
        # range that silently spanned two systems would describe neither, and
        # the gap between them is usually the finding.
        system = (span.get("system") or "").strip()
        subject = f"{system} on {where}" if system else where
        if lo == hi:
            text = (f"{studies} studies measured {subject} and all reported "
                    f"{_fmt(lo)}{u}.")
        elif studies < 3:
            # With two values the median is their midpoint — a number NO study
            # reported. The range already says everything the data supports.
            text = (f"Across {studies} studies, {subject} spans {_fmt(lo)}{u} "
                    f"to {_fmt(hi)}{u}.")
        else:
            text = (f"Across {studies} studies, {subject} spans {_fmt(lo)}{u} to "
                    f"{_fmt(hi)}{u} (median {_fmt(span.get('median', lo))}{u}).")
        out.append(_statement(text, dimension, doc_ids,
                              f"{studies} comparable measurements of {where}",
                              "pooled"))
    return out


def _direction_statements(dim: dict, dimension: str) -> list[dict]:
    """S2 — which system scored higher, counted across studies.

    Says "scored higher", never "performed better": higher is better for F1 and
    worse for latency, and nothing in the matrix records which way an axis
    points. That judgement is an I sentence, and I is not shipped.
    """
    out = []
    for row in dim.get("directions") or []:
        doc_ids = list(row.get("doc_ids") or [])
        studies = int(row.get("studies") or 0)
        if not doc_ids or studies < 2:
            continue
        a, b = row.get("system_a", ""), row.get("system_b", "")
        a_hi, b_hi = int(row.get("a_higher") or 0), int(row.get("b_higher") or 0)
        lead, n = (a, a_hi) if a_hi >= b_hi else (b, b_hi)
        where = _qualified(row)
        if a_hi == b_hi:
            text = (f"{studies} studies measured both {a} and {b} on {where}, "
                    f"and they split evenly — {a_hi} each way.")
        elif n == studies:
            text = (f"In all {studies} studies that measured both {a} and {b} "
                    f"on {where}, {lead} recorded the higher value.")
        else:
            text = (f"Of the {studies} studies that measured both {a} and {b} "
                    f"on {where}, {n} recorded a higher value for {lead}.")
        out.append(_statement(
            text, dimension, doc_ids,
            f"{studies} within-study comparisons of {a} against {b} on {where}",
            "direction"))
    return out


def derive_statements(synthesis: dict, matrix: list[dict]) -> list[dict]:
    """Turn a synthesis result into readable D sentences.

    Pure and deterministic: same matrix in, same sentences out, so two runs of
    one question stay comparable. Emits nothing it cannot substantiate — an axis
    whose studies cannot be named produces no sentence rather than a vague one.
    """
    dims = (synthesis or {}).get("dimensions") or []
    total = (synthesis or {}).get("studies_total") or 0
    if not dims or not total:
        return []

    out: list[dict] = []
    for dim in dims:
        name = (dim.get("dimension") or "").strip()
        studies = int(dim.get("studies") or 0)
        if not name or studies <= 0:
            continue
        doc_ids = _docs_reporting(matrix, name)
        if not doc_ids:
            # Counted somewhere but not attributable to rows: publishing it
            # would be a number the reader cannot follow back.
            continue

        largest = int(dim.get("largest_comparable_set") or 0)
        unexplained = int(dim.get("unexplained_contradictions") or 0)
        state = dim.get("state") or ""
        quantitative = (dim.get("kind") or "quantitative") == "quantitative"

        # ANSWER-LEVEL SENTENCES LEAD. Everything below the next two blocks is
        # meta-commentary about our corpus — true, useful, and not what the
        # reader came for. A researcher wants the pooled number and the
        # direction; the coverage and comparability caveats qualify them, so
        # they follow rather than open.
        out.extend(_direction_statements(dim, name))
        out.extend(_pooled_statements(dim, name))

        # ── coverage: how much of the corpus speaks to this axis at all ──
        verb = "reports" if studies == 1 else "report"
        out.append(_statement(
            f"{studies} of the {total} studies {verb} {name}.",
            name, doc_ids, dim.get("basis", ""), "coverage"))

        # ── comparability: the fact a fill-rate metric hides completely ──
        if quantitative and studies >= 2:
            if largest < 2:
                out.append(_statement(
                    f"No two of them measured {name} the same way — the same "
                    "metric on the same dataset and task — so these numbers "
                    "cannot be pooled or ranked against each other.",
                    name, doc_ids, dim.get("basis", ""), "comparability"))
            elif largest < studies:
                out.append(_statement(
                    f"Only {largest} of those {studies} measured {name} the "
                    "same way, so the remainder sit outside any shared "
                    "comparison.",
                    name, doc_ids, dim.get("basis", ""), "comparability"))

        # ── disagreement, already condition-checked by synthesis ──
        if unexplained:
            out.append(_statement(
                f"{_plural(unexplained, 'pair')} of those measurements disagree "
                "on the same quantity with no difference in the conditions the "
                "studies recorded to explain it.",
                name, doc_ids, dim.get("basis", ""), "contradiction"))

        # ── standing, stated as the count that produced it ──
        if state == STATE_STRONG:
            out.append(_statement(
                f"On this corpus {name} is the best-established axis: {studies} "
                f"independent studies with {largest} of them directly comparable.",
                name, doc_ids, dim.get("basis", ""), "standing"))
        elif state == STATE_INSUFFICIENT:
            out.append(_statement(
                f"Only one study here reports {name}, so nothing in this corpus "
                "can corroborate or contradict it.",
                name, doc_ids, dim.get("basis", ""), "standing"))
        elif state in (STATE_MODERATE, STATE_CONTESTED):
            pass  # already said by the comparability/disagreement sentences

    return out


def composition(verified_claims: int, derived: int, interpretive: int = 0) -> dict:
    """The header line that replaces "VERIFIED AGAINST SOURCES".

    That badge becomes false the moment a sentence ships that is not
    quote-verified. A composition count is both honest and more informative:
    it tells the reader what KINDS of sentence the report is made of before
    they read one.
    """
    return {
        "verified": verified_claims,
        "derived": derived,
        "inferred": interpretive,
        "note": ("verified = quote-matched and entailment-checked against a "
                 "source span; derived = computed from the study counts in the "
                 "evidence matrix and reproducible by recomputation"),
    }
