"""P1 G/H/I — synthesis that counts studies, not sentences.

The failure being prevented: a report that says "studies disagree about
GraphRAG latency" when one study measured on an A100 and the other on a laptop,
or that says "5 studies confirm 89% accuracy" when the five measured different
metrics on different datasets. Both read as rigor and are the opposite of it.

Every assertion below is on counts of STUDIES and their recorded conditions.
Nothing here consults an NLI score, by design — entailment says a sentence is
faithful to its source, which is a different question from how well established
a finding is.
"""

from app.agents.synthesis import (
    STATE_CONTESTED, STATE_EMERGING, STATE_INSUFFICIENT, STATE_MODERATE,
    STATE_STRONG, STATE_UNKNOWN, synthesize,
)


def _finding(dimension, value, *, metric="F1", dataset="HotpotQA",
             task="multi-hop QA", baseline="", model="", condition="",
             claim_id="cl", text="t"):
    return {"dimension": dimension, "metric": metric, "value": value,
            "claim_id": claim_id, "text": text, "chunk_id": "c", "quote": "q",
            "nli_label": "entailment", "nli_score": 0.99,
            "context": {"dataset": dataset, "task": task, "baseline": baseline,
                        "model": model, "condition": condition}}


def _study(doc_id, findings, title=None):
    return {"doc_id": doc_id, "title": title or f"Study {doc_id}", "year": 2026,
            "frameworks": [], "baselines": [], "datasets": [], "findings": findings}


def _dim(result, name):
    return next(d for d in result["dimensions"] if d["dimension"] == name)


def test_an_empty_matrix_synthesizes_to_nothing():
    out = synthesize([])
    assert out["dimensions"] == [] and out["studies_total"] == 0


def test_one_study_is_insufficient_not_supported():
    out = synthesize([_study("d1", [_finding("accuracy", "89.2%")])])
    assert _dim(out, "accuracy")["state"] == STATE_INSUFFICIENT
    assert "cross-check" in _dim(out, "accuracy")["basis"]


def test_two_studies_are_emerging():
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%")]),
        _study("d2", [_finding("accuracy", "88.0%")]),
    ])
    assert _dim(out, "accuracy")["state"] == STATE_EMERGING


def test_three_studies_are_moderately_supported():
    out = synthesize([
        _study(f"d{i}", [_finding("accuracy", f"8{i}.0%")]) for i in range(1, 4)
    ])
    assert _dim(out, "accuracy")["state"] == STATE_MODERATE


def test_five_comparable_studies_are_strongly_supported():
    """Strong requires both breadth (5 studies) and comparability (3 measured
    the same way) — breadth alone can be five studies measuring five things."""
    out = synthesize([
        _study(f"d{i}", [_finding("accuracy", f"88.{i}%")]) for i in range(1, 6)
    ])
    d = _dim(out, "accuracy")
    assert d["state"] == STATE_STRONG and d["largest_comparable_set"] == 5


def test_breadth_without_comparability_is_not_strong():
    """Five studies measuring five different things do not corroborate."""
    out = synthesize([
        _study(f"d{i}", [_finding("accuracy", "89.0%", dataset=f"Set{i}")])
        for i in range(1, 6)
    ])
    d = _dim(out, "accuracy")
    assert d["state"] == STATE_MODERATE
    assert d["largest_comparable_set"] == 1
    # The basis must not describe an agreement nobody could have measured. It
    # used to read "at most 1 of them measured it the same way, so the agreement
    # is real but thinly comparable" — self-contradicting, and disagreeing with
    # the `no_comparable_evidence` gap raised from the same numbers.
    assert "no two of them measured it the same way" in d["basis"]
    assert "cannot be pooled or ranked" in d["basis"]
    assert "thinly comparable" not in d["basis"]


# ── H: disagreement vs. different conditions ─────────────────────────────

def test_a_real_disagreement_is_flagged_as_unexplained():
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%")]),
        _study("d2", [_finding("accuracy", "62.0%")]),
    ])
    d = _dim(out, "accuracy")
    assert d["unexplained_contradictions"] == 1
    assert d["state"] == STATE_CONTESTED
    assert d["contradictions"][0]["explained"] is False


def test_a_difference_in_conditions_is_not_called_a_disagreement():
    """THE distinction: studies that tested different things are not in dispute."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%", model="GPT-4o")]),
        _study("d2", [_finding("accuracy", "62.0%", model="Llama-3-8B")]),
    ])
    d = _dim(out, "accuracy")
    assert d["contradictions"][0]["explained"] is True
    assert "model: GPT-4o vs Llama-3-8B" in d["contradictions"][0]["moderators"]
    assert d["unexplained_contradictions"] == 0
    assert d["state"] != STATE_CONTESTED


def test_an_unknown_condition_is_not_treated_as_a_matching_one():
    """If one study didn't state its model, we cannot dismiss the gap as a
    condition difference — the more damaging error is explaining away a real
    disagreement."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%", model="GPT-4o")]),
        _study("d2", [_finding("accuracy", "62.0%", model="")]),
    ])
    assert _dim(out, "accuracy")["unexplained_contradictions"] == 1


def test_incomparable_numbers_never_produce_a_contradiction():
    """Different metric on different data is not a dispute, it is two facts."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%", metric="F1", dataset="HotpotQA")]),
        _study("d2", [_finding("accuracy", "62.0%", metric="Recall@10", dataset="MuSiQue")]),
    ])
    d = _dim(out, "accuracy")
    assert d["contradictions"] == [] and d["comparable_sets"] == 2


def test_small_differences_are_not_contradictions():
    """89.2 vs 88.0 is benchmark noise, not a disagreement."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%")]),
        _study("d2", [_finding("accuracy", "88.0%")]),
    ])
    assert _dim(out, "accuracy")["contradictions"] == []


def test_a_level_and_a_delta_are_never_compared():
    """'89.2%' is a score and '+31.79%' is an improvement over a baseline;
    comparing them as numbers is a category error, not a finding."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%")]),
        _study("d2", [_finding("accuracy", "+31.79%")]),
    ])
    assert _dim(out, "accuracy")["contradictions"] == []


def test_two_findings_from_one_study_are_not_a_cross_study_disagreement():
    """A paper reporting several conditions is not the field disagreeing."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%"), _finding("accuracy", "51.0%")]),
    ])
    d = _dim(out, "accuracy")
    assert d["contradictions"] == [] and d["studies"] == 1


# ── G: coverage across the corpus ────────────────────────────────────────

def test_coverage_shows_which_axes_the_field_actually_measures():
    """The raw material for research gaps: accuracy measured by everyone,
    cost by almost nobody."""
    matrix = [_study(f"d{i}", [_finding("accuracy", f"8{i}.0%")]) for i in range(1, 6)]
    matrix[0]["findings"].append(
        _finding("production cost", "12.50 USD", metric="cost", dataset="internal"))
    out = synthesize(matrix)

    assert _dim(out, "accuracy")["corpus_coverage"] == 1.0
    assert _dim(out, "production cost")["corpus_coverage"] == 0.2
    assert _dim(out, "production cost")["state"] == STATE_INSUFFICIENT
    # Most-measured first — the ordering is itself the coverage story.
    assert out["dimensions"][0]["dimension"] == "accuracy"


def test_value_spans_need_two_studies():
    """A range drawn from one paper is that paper's opinion, not the field's."""
    out = synthesize([
        _study("d1", [_finding("accuracy", "89.2%"), _finding("accuracy", "70.0%")]),
    ])
    assert _dim(out, "accuracy")["value_spans"] == []


def test_the_output_states_that_strength_is_not_entailment():
    """Anyone reading this JSON later must not mistake it for an NLI score."""
    out = synthesize([_study("d1", [_finding("accuracy", "89.2%")])])
    assert "never from NLI entailment" in out["note"]


def test_unknown_state_is_reachable_only_with_no_studies():
    out = synthesize([_study("d1", [_finding("accuracy", "89.2%")])])
    assert all(d["state"] != STATE_UNKNOWN for d in out["dimensions"])


def test_synthesis_is_deterministic():
    matrix = [_study(f"d{i}", [_finding("accuracy", f"8{i}.0%")]) for i in range(1, 5)]
    assert synthesize(matrix) == synthesize(list(reversed(matrix)))


def test_legacy_matrices_without_context_still_synthesize():
    """Matrices written before P1-E have no context field; they must degrade to
    'not comparable' rather than crash or silently pool."""
    legacy = [{"doc_id": "d1", "title": "S", "findings": [
        {"dimension": "accuracy", "metric": "F1", "value": "89.2%",
         "claim_id": "c", "text": "t"}]}]
    out = synthesize(legacy)
    d = _dim(out, "accuracy")
    assert d["studies"] == 1 and d["comparable_sets"] == 0
