"""A missing shared benchmark is only a gap where a measurement was expected.

`no_comparable_evidence` says: several studies report this axis, but no two
measured it the same way, so the numbers cannot be pooled. That is a real and
subtle hole — and it is nonsense applied to an axis nobody was measuring.

On a live report it fired on all five axes, including "architectural
complexity" and "limitation", producing five near-identical complaints that
buried the one that mattered. The axis kind comes from the run's evidence
schema, which already distinguishes quantitative from qualitative.
"""

from app.agents.synthesis import research_gaps, synthesize

KINDS = {"architectural complexity": "qualitative",
         "retrieval accuracy": "quantitative"}


def _studies(dimension, n=3, quantified=False):
    rows = []
    for i in range(n):
        finding = {
            "claim_id": f"c{dimension}{i}", "dimension": dimension,
            "text": "A finding.", "metric": "", "value": "", "context": {},
        }
        if quantified:
            finding |= {
                "metric": ["F1", "Recall@10", "EM"][i % 3],
                "value": ["88.1%", "72.0%", "45.4%"][i % 3],
                "context": {"dataset": ["HotpotQA", "MuSiQue", "NQ"][i % 3], "task": "QA"},
            }
        rows.append({"doc_id": f"d{dimension}{i}", "title": f"Study {i}",
                     "findings": [finding]})
    return rows


def _kinds_of(matrix):
    return [g["kind"] for g in research_gaps(synthesize(matrix, dimension_kinds=KINDS))]


def test_qualitative_axis_is_not_faulted_for_lacking_a_shared_benchmark():
    assert "no_comparable_evidence" not in _kinds_of(
        _studies("architectural complexity", quantified=False))


def test_quantitative_axis_measured_incomparably_is_still_a_gap():
    assert "no_comparable_evidence" in _kinds_of(
        _studies("retrieval accuracy", quantified=True))


def test_an_axis_with_almost_no_numbers_is_not_a_comparability_gap():
    """Two unparsed values are not evidence that a shared benchmark is missing —
    they are evidence that nothing was quantified, which is a different problem
    and must not be reported as this one."""
    assert "no_comparable_evidence" not in _kinds_of(
        _studies("retrieval accuracy", quantified=False))


def test_kind_defaults_to_quantitative_when_the_schema_is_absent():
    """Older runs carry no schema. The gap must still be reachable, or the
    behaviour would silently regress for every report already in the database."""
    gaps = research_gaps(synthesize(_studies("retrieval accuracy", quantified=True)))
    assert "no_comparable_evidence" in [g["kind"] for g in gaps]


def test_single_study_gap_is_unaffected_by_kind():
    gaps = research_gaps(synthesize(_studies("architectural complexity", n=1),
                                    dimension_kinds=KINDS))
    assert [g["kind"] for g in gaps] == ["single_study"]
