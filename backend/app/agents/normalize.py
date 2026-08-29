"""Quantitative evidence normalization (P1-E).

THE PROBLEM. The matrix stores a finding's headline number as free text —
"89.2", "+31.79%", "9.03s". Downstream that is enough to RENDER a cell but not
enough to REASON across studies, and the difference matters the moment anyone
counts: two studies both reporting "89.2" may be measuring F1 on HotpotQA and
Recall@10 on MuSiQue, which is not agreement. A synthesis layer that treats them
as the same datapoint manufactures a consensus that does not exist — a subtler
version of the fabrication this system exists to prevent, because every
individual number is real and correctly quoted.

So a quantitative finding carries its CONTEXT, and comparability is a computed
property rather than an assumption:

    89.2 F1 · HotpotQA · multi-hop QA · vs Vector RAG · GPT-4 · top_k=10

Two findings are comparable only when they measure the same axis with the same
metric on the same dataset and task. Anything less is "related, not comparable",
and the synthesis layer must say which it is.

Everything here is deterministic string/number handling — no model calls, no
judgment. The context fields themselves come from the extractor (which quotes
them from the paper); this module only parses, canonicalizes and compares.
"""

import re
from dataclasses import dataclass, field

# A leading sign, a number, and an optional unit. Deliberately tolerant of the
# ways papers write deltas: "+31.79%", "-13.4pp", "1.4M tokens", "9.03 s".
_VALUE = re.compile(
    r"^\s*(?P<sign>[+\-−±]?)\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>[kKmMbB](?![a-zA-Z]))?\s*(?P<unit>[^\d\s]*[a-zA-Z%°/]*)",
)

_SCALES = {"k": 1e3, "m": 1e6, "b": 1e9}

# Unit spellings that mean the same thing. Kept small and uncontroversial: a
# unit table is a place where over-eager merging silently rewrites evidence, so
# only exact synonyms belong here — never "s" -> "ms" style conversions, which
# would change the number a reader sees quoted next to its source.
_UNIT_CANON = {
    "%": "%", "percent": "%", "pct": "%", "pp": "pp", "points": "pp",
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "ms": "ms", "msec": "ms", "milliseconds": "ms", "millisecond": "ms",
    "min": "min", "mins": "min", "minute": "min", "minutes": "min",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "tokens": "tokens", "token": "tokens", "tok": "tokens",
    "usd": "usd", "$": "usd", "dollars": "usd", "dollar": "usd",
    "gb": "gb", "mb": "mb", "kb": "kb",
    "qps": "qps", "rps": "qps", "queries/sec": "qps",
    "x": "x", "×": "x", "fold": "x",
}

# Metric names normalized for comparison only (the displayed text is untouched).
_METRIC_CANON = {
    "f1": "f1", "f-1": "f1", "f1-score": "f1", "f1 score": "f1",
    "em": "em", "exact match": "em", "exact-match": "em",
    "acc": "accuracy", "accuracy": "accuracy",
    "precision": "precision", "recall": "recall",
    "ndcg": "ndcg", "mrr": "mrr", "map": "map",
    "latency": "latency", "response time": "latency",
    "throughput": "throughput", "cost": "cost",
}


def _canon(value: str, table: dict[str, str]) -> str:
    key = " ".join((value or "").split()).strip().lower().rstrip(".")
    return table.get(key, key)


@dataclass
class Quantity:
    """A parsed measurement. `raw` is always preserved — the reader sees what the
    paper wrote, never our reconstruction of it."""
    raw: str
    number: float | None = None
    unit: str = ""
    signed: bool = False       # the paper reported it as a DELTA (+/-), not a level

    @property
    def ok(self) -> bool:
        return self.number is not None


# A COMPOUND value: two numbers packed into one field, e.g. "57.67/68.53" for a
# paper reporting EM/F1 together. Seen in the wild on the calibration corpus.
# Parsing it would silently keep the first number and drop the second, so the
# matrix would carry "57.67" as if that were the finding. It is not one
# measurement, so it is not a quantity — it stays qualitative and out of every
# comparable bucket.
_COMPOUND = re.compile(r"\d\s*[/±]\s*\d")


def parse_quantity(value: str) -> Quantity:
    """Parse a headline value into number + unit. Never raises; an unparseable
    value simply stays qualitative, which is a legitimate outcome."""
    if not value or not value.strip():
        return Quantity(raw=value or "")
    if _COMPOUND.search(value):
        return Quantity(raw=value.strip())
    m = _VALUE.match(value)
    if not m:
        return Quantity(raw=value)
    try:
        num = float(m.group("num").replace(",", ""))
    except ValueError:
        return Quantity(raw=value)
    scale = (m.group("scale") or "").lower()
    if scale in _SCALES:
        num *= _SCALES[scale]
    sign = m.group("sign") or ""
    if sign in ("-", "−"):
        num = -num
    unit = _canon(m.group("unit") or "", _UNIT_CANON)
    return Quantity(raw=value.strip(), number=num, unit=unit,
                    signed=sign in ("+", "-", "−"))


@dataclass
class EvidencePoint:
    """One normalized quantitative datapoint, with the context that decides
    whether it may be compared with another."""
    doc_id: str
    study: str
    dimension: str
    claim_id: str = ""
    metric: str = ""
    quantity: Quantity = field(default_factory=lambda: Quantity(raw=""))
    dataset: str = ""
    task: str = ""
    baseline: str = ""
    model: str = ""
    condition: str = ""
    text: str = ""

    @property
    def comparable_key(self) -> tuple[str, str, str, str]:
        """What must match before two numbers are the same measurement.

        Dimension AND metric AND dataset AND task. Dropping any one of these is
        how "GraphRAG scores 89.2" and "GraphRAG scores 89.2" become false
        corroboration of each other.
        """
        return (self.dimension.lower(), _canon(self.metric, _METRIC_CANON),
                self.dataset.lower().strip(), self.task.lower().strip())

    @property
    def context_known(self) -> bool:
        """Do we know enough about this number to compare it with anything?"""
        return bool(self.metric and (self.dataset or self.task))


def point_from_finding(doc_id: str, study: str, finding: dict) -> EvidencePoint:
    ctx = finding.get("context") or {}
    return EvidencePoint(
        doc_id=doc_id, study=study,
        dimension=(finding.get("dimension") or "").strip(),
        claim_id=finding.get("claim_id", ""),
        metric=(finding.get("metric") or "").strip(),
        quantity=parse_quantity(finding.get("value") or ""),
        dataset=(ctx.get("dataset") or "").strip(),
        task=(ctx.get("task") or "").strip(),
        baseline=(ctx.get("baseline") or "").strip(),
        model=(ctx.get("model") or "").strip(),
        condition=(ctx.get("condition") or "").strip(),
        text=finding.get("text", ""),
    )


def comparable(a: EvidencePoint, b: EvidencePoint) -> bool:
    """Same measurement, different study? Both must be parsed numbers on the
    same axis/metric/dataset/task. Unknown context is NOT treated as matching —
    an empty dataset field means we don't know, not that they agree."""
    if not (a.quantity.ok and b.quantity.ok):
        return False
    if not (a.context_known and b.context_known):
        return False
    if a.quantity.unit != b.quantity.unit:
        return False
    return a.comparable_key == b.comparable_key


def group_comparable(points: list[EvidencePoint]) -> dict[tuple, list[EvidencePoint]]:
    """Bucket points into genuinely comparable sets. Points whose context is
    unknown are kept OUT of every bucket rather than pooled into a default one:
    a nameless bucket is exactly where incomparable numbers get averaged."""
    buckets: dict[tuple, list[EvidencePoint]] = {}
    for p in points:
        if not (p.quantity.ok and p.context_known):
            continue
        key = (*p.comparable_key, p.quantity.unit)
        buckets.setdefault(key, []).append(p)
    return buckets


def describe_context(p: EvidencePoint) -> str:
    """Human-readable qualification for a number, e.g.
    'F1 · HotpotQA · multi-hop QA · vs Vector RAG'. Empty when nothing is known,
    which is itself the honest signal that the number stands unqualified."""
    parts = [p.metric, p.dataset, p.task]
    if p.baseline:
        parts.append("vs " + p.baseline)
    if p.model:
        parts.append(p.model)
    if p.condition:
        parts.append(p.condition)
    return " · ".join(x for x in parts if x)


# ── S3: entity identity ───────────────────────────────────────────────────
#
# The pivot from study x dimension to SYSTEM x dimension needs to know when two
# strings name the same system. `context.model` is free text an extractor copied
# out of a paper, so the same system arrives as "GraphRAG", "Graph-RAG",
# "GraphRAG (ours)" and "graphrag".
#
# THE ASYMMETRY THAT SETS THE RULES. Under-merging costs a duplicated row, which
# a reader sees and can discount. Over-merging silently fuses two systems'
# results into one, which is a fabricated finding no gate can catch — every
# number in it is real and correctly quoted. So this canonicalizer is
# deliberately conservative:
#
#   - punctuation, spacing and case are removed (they never distinguish two
#     systems: "Llama-3.1-8B" and "Llama 3.1 8B" are one system);
#   - NOTHING fuzzy. No edit distance, no prefix matching, no stemming.
#     "GPT-4" and "GPT-4o" are one character apart and are different models.
#
# Every merge is auditable: callers keep the alias set, so a wrong merge shows
# up in the report as a row naming both spellings rather than as a silent join.

# Strings that occupy the model field but do not name a system. "ours" and
# "baseline" are relational labels — they mean different systems in different
# papers, so merging on them would pool unrelated results under one row.
_NOT_AN_ENTITY = {
    "", "-", "--", "n/a", "na", "none", "null", "unknown", "unspecified",
    "ours", "our", "ourmethod", "ourmodel", "ourapproach", "oursystem",
    "proposed", "proposedmethod", "proposedmodel", "proposedapproach",
    "baseline", "baselines", "thebaseline", "standard", "default",
    "model", "themodel", "system", "thesystem", "method", "themethod",
    "all", "allmodels", "various", "other", "others", "etc",
}

# Trailing decorations a paper adds to its own system's name.
_ENTITY_ASIDE = re.compile(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*$")


def canonical_entity(name: str) -> str:
    """Identity key for a system name, or "" when the string names no system.

    Returns a MATCHING key, never a display string — see `entity_display` for
    what a reader should be shown.
    """
    if not name:
        return ""
    text = name.strip()
    # Drop one trailing aside: "GraphRAG (ours)" -> "GraphRAG". Repeated so
    # "LightRAG (ours) [2024]" reduces fully.
    for _ in range(3):
        stripped = _ENTITY_ASIDE.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    key = re.sub(r"[^a-z0-9]+", "", text.lower())
    if key in _NOT_AN_ENTITY:
        return ""
    # A bare number is a value that leaked into the model field, not a system.
    if key.isdigit():
        return ""
    return key


def entity_display(names: list[str]) -> str:
    """The spelling to SHOW for a set of aliases that share a canonical key.

    The most frequent spelling wins, ties broken alphabetically so two runs of
    one question render the same name. Deliberately not "the longest" or "the
    first seen": both let one odd extraction rename a system everywhere.
    """
    counts: dict[str, int] = {}
    for raw in names:
        cleaned = _ENTITY_ASIDE.sub("", (raw or "").strip()).strip()
        if cleaned:
            counts[cleaned] = counts.get(cleaned, 0) + 1
    if not counts:
        return ""

    def _rank(item: tuple[str, int]) -> tuple:
        spelling, count = item
        # Frequency first. On a tie, prefer the PLAINEST spelling — fewest
        # punctuation marks, then shortest — because decoration is what varies
        # between papers writing the same name ("Graph-RAG" vs "GraphRAG").
        # A bare alphabetical tie-break would systematically favour hyphenated
        # forms, since '-' sorts below every letter.
        punctuation = sum(1 for ch in spelling if not ch.isalnum())
        return (-count, punctuation, len(spelling), spelling)

    # A tie on every criterion is genuinely arbitrary; it is resolved
    # deterministically so two runs agree, and the full alias set travels with
    # the row so the reader sees what was folded together either way.
    return sorted(counts.items(), key=_rank)[0][0]
