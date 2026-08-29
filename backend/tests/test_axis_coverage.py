"""Tell the researcher what the corpus can answer BEFORE the 40-minute run.

The expensive failure is not a bad paper. It is discovering, forty minutes and
twenty-six PDFs later, that the corpus was never going to answer one of the axes
the question needs — which is how a five-study review came back with "no
comparable evidence" on every axis.

The probe counts, per required axis, how many screened-in candidates even
MENTION it. It is deliberately a keyword count: free, so it can run before the
commit, and a fair UPPER bound, since an abstract that never uses the word is
unlikely to carry the measurement.
"""

from app.services.screening import _axis_pattern, _axis_terms, axis_coverage


def _cand(title, abstract, recommend="keep"):
    return {"title": title, "abstract": abstract, "recommend": recommend}


SCHEMA = {"required_dimensions": [
    {"name": "retrieval accuracy", "synonyms": ["recall"], "metrics": ["f1", "%"]},
    {"name": "latency", "synonyms": ["throughput"], "metrics": ["ms"]},
    {"name": "cost", "synonyms": ["dollars"], "metrics": ["usd"]},
]}


def test_short_metric_names_are_kept():
    """f1, em and ms are the most common metric names in this literature. A
    length filter that dropped them reported an axis every paper measured as
    'barely present'."""
    terms = _axis_terms({"name": "accuracy", "synonyms": [], "metrics": ["f1", "EM", "%"]})
    assert "f1" in terms and "em" in terms
    assert "%" not in terms          # single characters match everything


def test_matching_respects_word_boundaries():
    """Substring matching is what made short tokens unusable: 'ms' must fire on
    '12 ms' and never on 'systems'."""
    p = _axis_pattern(["ms", "f1"])
    assert p.search("median latency was 12 ms under load")
    assert not p.search("distributed systems and other terms")


def test_axes_are_counted_over_kept_candidates_only():
    cands = [
        _cand("Fast retrieval", "We measure latency and throughput in ms."),
        _cand("Accurate graphs", "F1 and recall on HotpotQA."),
        _cand("Cost study", "Reported in dollars per query", recommend="drop"),
    ]
    rows = {r["axis"]: r for r in axis_coverage(cands, SCHEMA)}
    assert rows["latency"]["candidates_kept"] == 2
    assert rows["cost"]["candidates_mentioning"] == 0   # the only cost paper was dropped


def test_an_uncovered_axis_is_reported_first():
    """The reader is deciding whether to spend 40 minutes; the weakest axis is
    the one that changes that decision, so it leads."""
    cands = [_cand("Accuracy", "recall and f1"), _cand("More accuracy", "f1 scores")]
    rows = axis_coverage(cands, SCHEMA)
    assert rows[0]["candidates_mentioning"] == 0
    assert rows[0]["verdict"] == "barely present"


def test_verdicts_are_named_thresholds_not_scores():
    cands = [_cand("A", "recall"), _cand("B", "recall"), _cand("C", "unrelated")]
    rows = {r["axis"]: r for r in axis_coverage(cands, SCHEMA)}
    assert rows["retrieval accuracy"]["verdict"] == "well covered"   # 2/3
    assert rows["cost"]["verdict"] == "barely present"               # 0/3


def test_no_schema_yields_no_coverage_rather_than_a_false_all_clear():
    assert axis_coverage([_cand("A", "b")], {}) == []
    assert axis_coverage([_cand("A", "b")], {"required_dimensions": []}) == []


def test_no_kept_candidates_does_not_divide_by_zero():
    rows = axis_coverage([_cand("A", "b", recommend="drop")], SCHEMA)
    assert all(r["share"] == 0.0 and r["candidates_kept"] == 0 for r in rows)
