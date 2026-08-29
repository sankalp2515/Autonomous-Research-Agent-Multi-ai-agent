"""P1-E — two identical numbers are not automatically the same result.

The failure this prevents is quiet and severe: a synthesis layer that counts
"how many studies report 89.2 accuracy" will happily add together an F1 on
HotpotQA and a Recall@10 on MuSiQue. Every individual number is real and
correctly quoted, so nothing in the grounding gate can catch it — the fabrication
happens in the AGGREGATION. These tests pin comparability as a computed property
with unknown context defaulting to "not comparable".
"""

import pytest

from app.agents.normalize import (
    EvidencePoint, comparable, describe_context, group_comparable,
    parse_quantity, point_from_finding,
)


@pytest.mark.parametrize("raw,number,unit", [
    ("89.2%", 89.2, "%"),
    ("+31.79%", 31.79, "%"),
    ("-13.4pp", -13.4, "pp"),
    ("9.03s", 9.03, "s"),
    ("9.03 s", 9.03, "s"),
    ("120 ms", 120.0, "ms"),
    ("1.4M tokens", 1_400_000.0, "tokens"),
    ("1,024 tokens", 1024.0, "tokens"),
    ("12.50 USD", 12.5, "usd"),
    ("2.3x", 2.3, "x"),
    ("0.847", 0.847, ""),
])
def test_headline_values_parse(raw, number, unit):
    q = parse_quantity(raw)
    assert q.ok and q.number == pytest.approx(number) and q.unit == unit
    assert q.raw == raw, "the paper's own wording must survive parsing"


@pytest.mark.parametrize("raw", ["", "substantially higher", "N/A", "improved"])
def test_qualitative_values_stay_qualitative(raw):
    """An unparseable value is a legitimate outcome, not an error to paper over."""
    assert parse_quantity(raw).ok is False


@pytest.mark.parametrize("raw", ["57.67/68.53", "0.45 / 0.62", "88.1±0.4"])
def test_compound_values_are_not_reduced_to_their_first_number(raw):
    """Seen on the real corpus: a paper reporting EM/F1 as '57.67/68.53'. Keeping
    only 57.67 would put a number in the matrix that is not the finding, and it
    would then be compared against other studies as though it were."""
    q = parse_quantity(raw)
    assert q.ok is False and q.raw == raw


def test_a_delta_is_flagged_as_a_delta():
    """'+31.79%' is an improvement over something; '89.2%' is a level. Treating
    the first as the second is a silent unit error."""
    assert parse_quantity("+31.79%").signed is True
    assert parse_quantity("89.2%").signed is False


def _point(**kw):
    base = dict(doc_id="d", study="S", dimension="generation accuracy",
                metric="F1", dataset="HotpotQA", task="multi-hop QA")
    base.update(kw)
    q = parse_quantity(base.pop("value", "89.2%"))
    return EvidencePoint(quantity=q, **base)


def test_same_measurement_is_comparable():
    a = _point(doc_id="d1", value="89.2%")
    b = _point(doc_id="d2", value="86.5%")
    assert comparable(a, b)


def test_same_number_different_metric_is_not_comparable():
    a = _point(doc_id="d1", metric="F1", value="89.2%")
    b = _point(doc_id="d2", metric="Recall@10", value="89.2%")
    assert not comparable(a, b), "F1 and Recall@10 were treated as one measurement"


def test_same_number_different_dataset_is_not_comparable():
    a = _point(doc_id="d1", dataset="HotpotQA", value="89.2%")
    b = _point(doc_id="d2", dataset="MuSiQue", value="89.2%")
    assert not comparable(a, b)


def test_different_units_are_not_comparable():
    a = _point(doc_id="d1", dimension="latency", metric="latency",
               value="120 ms", dataset="HotpotQA")
    b = _point(doc_id="d2", dimension="latency", metric="latency",
               value="9.03 s", dataset="HotpotQA")
    assert not comparable(a, b), (
        "ms and s were pooled — a unit conversion is a judgment the reader "
        "should see, not one this layer should make silently")


def test_unknown_context_is_never_assumed_to_match():
    """Two bare numbers with no dataset or task are not evidence of agreement."""
    a = _point(doc_id="d1", dataset="", task="", value="89.2%")
    b = _point(doc_id="d2", dataset="", task="", value="89.2%")
    assert not comparable(a, b)


def test_qualitative_points_are_never_comparable():
    a = _point(doc_id="d1", value="substantially better")
    b = _point(doc_id="d2", value="substantially better")
    assert not comparable(a, b)


def test_grouping_excludes_unqualified_numbers_rather_than_pooling_them():
    """An unnamed bucket is exactly where incomparable numbers get averaged."""
    points = [
        _point(doc_id="d1", value="89.2%"),
        _point(doc_id="d2", value="86.5%"),
        _point(doc_id="d3", dataset="", task="", value="91.0%"),   # unqualified
        _point(doc_id="d4", dataset="MuSiQue", value="77.0%"),     # other dataset
    ]
    buckets = group_comparable(points)
    sizes = sorted(len(v) for v in buckets.values())
    assert sizes == [1, 2], f"unexpected bucketing: {sizes}"
    assert all(len(b) for b in buckets.values())
    pooled = {p.doc_id for b in buckets.values() for p in b}
    assert "d3" not in pooled, "an unqualified number was pooled into a bucket"


def test_a_finding_carries_its_context_through():
    finding = {
        "dimension": "generation accuracy", "metric": "F1", "value": "89.2%",
        "claim_id": "cl1", "text": "GraphRAG reaches 89.2 F1.",
        "context": {"dataset": "HotpotQA", "task": "multi-hop QA",
                    "baseline": "Vector RAG", "model": "GPT-4o",
                    "condition": "top_k=10"},
    }
    p = point_from_finding("d1", "A Paper", finding)
    assert p.quantity.number == pytest.approx(89.2)
    assert p.context_known
    assert describe_context(p) == "F1 · HotpotQA · multi-hop QA · vs Vector RAG · GPT-4o · top_k=10"


def test_a_finding_without_context_says_so():
    p = point_from_finding("d1", "A Paper", {
        "dimension": "accuracy", "metric": "", "value": "89.2%", "text": "t"})
    assert not p.context_known
    assert describe_context(p) == ""


def test_legacy_findings_without_a_context_field_still_load():
    """Backward compatibility: matrices written before P1-E have no context key."""
    p = point_from_finding("d1", "A Paper", {
        "dimension": "accuracy", "metric": "F1", "value": "89.2%", "text": "t"})
    assert p.quantity.ok and p.dataset == ""
