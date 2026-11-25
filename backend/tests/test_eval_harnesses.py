"""The benchmark harnesses' own logic, tested without the benchmarks.

A harness that miscounts is worse than none: its number gets quoted. These pin
the parts that turn raw outcomes into published rates — case construction,
the offline replay of the gate decision, population re-weighting — on tiny
synthetic inputs whose right answers are known by hand.
"""

import pytest

from evals import scifact_gate as sf
from evals import screening_bench as sb
from evals.stats import rate, wilson


def test_wilson_interval_is_sane_at_the_edges():
    lo, hi = wilson(0, 12)
    assert lo == 0.0 and 0.2 < hi < 0.3          # 0/12 is NOT "[0, 0]"
    lo, hi = wilson(12, 12)
    assert hi == 1.0 and 0.7 < lo < 0.8
    assert rate(0, 0)["rate"] is None


CORPUS = {
    1: {"doc_id": 1, "title": "Paper one",
        "abstract": ["Background sentence here.", "Drug X lowered blood pressure by 10 mmHg.",
                     "Unrelated methods detail about sampling."]},
}


def test_scifact_cases_use_the_gold_rationale_and_a_realistic_nei_quote():
    claims = [
        {"id": 1, "claim": "Drug X lowers blood pressure.",
         "evidence": {"1": [{"sentences": [1], "label": "SUPPORT"}]}, "cited_doc_ids": [1]},
        {"id": 2, "claim": "Drug X raises blood pressure.",
         "evidence": {"1": [{"sentences": [1], "label": "CONTRADICT"}]}, "cited_doc_ids": [1]},
        {"id": 3, "claim": "Drug X causes blood pressure headaches in children.",
         "evidence": {}, "cited_doc_ids": [1]},
        {"id": 4, "claim": "cites a doc not in the corpus", "evidence": {}, "cited_doc_ids": [99]},
    ]
    cases = {c["claim_id"]: c for c in sf.build_cases(claims, CORPUS)}
    assert set(cases) == {1, 2, 3}
    assert cases[1]["label"] == "SUPPORT" and "10 mmHg" in cases[1]["quote"]
    assert cases[2]["label"] == "CONTRADICT" and cases[2]["quote"] == cases[1]["quote"]
    # NEI picks the sentence sharing the most content words with the claim.
    assert cases[3]["label"] == "NEI" and "blood pressure" in cases[3]["quote"]
    for c in cases.values():
        assert c["quote"] in c["chunk"], "the quote must be verbatim in the chunk"


def _row(label, probs, reason="ok", verified=None):
    top = max(probs, key=probs.get)
    return {"label": label, "probs": probs, "reason": reason, "nli_label": top,
            "nli_score": probs[top], "verified": verified}


def test_offline_decision_reproduces_the_shipped_layer3_rule():
    # contradiction 0.40 / neutral 0.85 / no entailment floor = gate._apply_nli
    assert sf.decide(_row("x", {"entailment": .2, "neutral": .3, "contradiction": .5}), .4, .85, 0) is False
    assert sf.decide(_row("x", {"entailment": .05, "neutral": .9, "contradiction": .05}), .4, .85, 0) is False
    # weak neutral passes the shipped gate - the case the sweep exists to price
    assert sf.decide(_row("x", {"entailment": .2, "neutral": .7, "contradiction": .1}), .4, .85, 0) is True
    assert sf.decide(_row("x", {"entailment": .2, "neutral": .7, "contradiction": .1}), .4, .85, .5) is False
    assert sf.decide(_row("x", {"entailment": .9}, reason="quote_mismatch"), .4, .85, 0) is False


def test_scifact_score_counts_false_accepts_by_label():
    rows = [_row("SUPPORT", {"entailment": 1.0}, verified=True),
            _row("SUPPORT", {"entailment": 1.0}, verified=False),
            _row("CONTRADICT", {"entailment": 1.0}, verified=True),
            _row("NEI", {"entailment": 1.0}, verified=False)]
    s = sf.score(rows)
    assert s["false_accept_contradict"]["k"] == 1 and s["false_accept_contradict"]["n"] == 1
    assert s["false_accept_nei"]["k"] == 0
    assert s["false_reject_support"]["k"] == 1
    assert s["verified_precision"]["k"] == 1 and s["verified_precision"]["n"] == 2


def test_the_sweep_cannot_win_by_refusing_everything():
    points = [{"contradiction": .4, "neutral": .1, "entail_min": .99, "fa": 0.0, "fr": 1.0},
              {"contradiction": .4, "neutral": .85, "entail_min": .5, "fa": 0.1, "fr": 0.15}]
    assert sf._pick(points, max_fr=0.2)["entail_min"] == .5


def _recs(pos_kept, pos_missed, neg_kept, neg_dropped):
    recs, kept = [], set()
    for i in range(pos_kept + pos_missed):
        recs.append(sb.Record(f"p{i}", f"pos {i}", "", 2005, 1))
        if i < pos_kept:
            kept.add(f"p{i}")
    for i in range(neg_kept + neg_dropped):
        recs.append(sb.Record(f"n{i}", f"neg {i}", "", 2005, 0))
        if i < neg_kept:
            kept.add(f"n{i}")
    return recs, kept


def test_screening_metrics_reweight_precision_to_the_true_prevalence():
    # 9/10 positives kept; 2/100 sampled negatives kept; population 10 pos + 990 neg
    recs, kept = _recs(9, 1, 2, 98)
    m = sb.metrics(recs, kept, population=1000, population_pos=10)
    assert m["recall"]["rate"] == 0.9
    assert m["specificity"]["rate"] == 0.98
    # sample precision would be 9/11 = 82%; at 1% prevalence it is far lower
    assert m["precision_at_prevalence"] == pytest.approx(0.9 * .01 / (0.9 * .01 + .02 * .99), abs=1e-4)
    # WSS@R = (TN + FN)/N - (1 - R) on the population scale
    assert m["wss_at_recall"] == pytest.approx((0.98 * 990 + 0.1 * 10) / 1000 - 0.1, abs=1e-4)


def test_screening_sample_keeps_every_positive_and_is_seeded():
    recs = [sb.Record(f"p{i}", f"p{i}", "", None, 1) for i in range(5)] + \
           [sb.Record(f"n{i}", f"n{i}", "", None, 0) for i in range(500)]
    a, b = sb.sample(recs, 50, seed=3), sb.sample(recs, 50, seed=3)
    assert [r.record_id for r in a] == [r.record_id for r in b]
    assert sum(r.label for r in a) == 5 and len(a) == 55
