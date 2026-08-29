"""P1-F — the research funnel must account for every paper, with reasons.

WHY. The old funnel was five counts and one aggregate — "5/5 sub-questions
grounded" — which a reader takes as "the literature was covered". It is not
that. It is a statement about the REPORT: every section found something it could
verify. Meanwhile the papers that left the funnel disappeared into a single
"screened out" number, so a paper rejected as off-topic, one that was paywalled,
and one the extractor could not read were indistinguishable — even though only
the first is a judgment about relevance and only the third is a failure of ours.

These tests pin that each drop is recorded where it happens, with its reason,
and that the stages stay separate.
"""

import time

from app.agents import nodes


def _state():
    return {"run_id": "r", "project_id": "p", "query": "q",
            "llm_calls_used": 0, "started_at": time.time(),
            "coverage_notes": [], "funnel": {}, "exclusions": [],
            "exclusion_counts": {}}


def test_an_exclusion_records_paper_stage_and_reason():
    state = _state()
    nodes._exclude(state, "A Paper", "citation_floor", "3 citations, below 50")

    assert state["exclusions"] == [
        {"title": "A Paper", "stage": "citation_floor",
         "reason": "3 citations, below 50"}]
    assert state["exclusion_counts"] == {"citation_floor": 1}


def test_reasons_are_counted_per_stage_not_pooled():
    """A single 'excluded: 9' number is what this replaces."""
    state = _state()
    for i in range(3):
        nodes._exclude(state, f"P{i}", "screened_out", "off topic")
    nodes._exclude(state, "P4", "no_text_available", "paywalled")
    nodes._exclude(state, "P5", "extraction_failed", "nothing passed the gate")

    assert state["exclusion_counts"] == {
        "screened_out": 3, "no_text_available": 1, "extraction_failed": 1}


def test_the_exclusion_list_is_bounded_but_the_counts_are_not():
    """A pathological run must not grow the checkpoint without limit — yet the
    tallies must stay correct, because they are what the report renders."""
    state = _state()
    for i in range(nodes._MAX_EXCLUSIONS + 50):
        nodes._exclude(state, f"P{i}", "screened_out", "off topic")

    assert len(state["exclusions"]) == nodes._MAX_EXCLUSIONS
    assert state["exclusion_counts"]["screened_out"] == nodes._MAX_EXCLUSIONS + 50


def test_long_titles_and_reasons_are_truncated_not_dropped():
    state = _state()
    nodes._exclude(state, "T" * 500, "screened_out", "R" * 500)
    row = state["exclusions"][0]
    assert len(row["title"]) == 120 and len(row["reason"]) == 200


def test_an_untitled_paper_still_gets_a_row():
    state = _state()
    nodes._exclude(state, "", "over_ingest_cap", "beyond the cap")
    assert state["exclusions"][0]["title"] == "untitled"


def test_every_ladder_stage_is_named():
    """The stages are a contract with the report renderer; renaming one silently
    empties a row of the funnel the reader sees."""
    assert nodes.FUNNEL_STAGES == (
        "discovered", "screened", "eligible", "full_text_available",
        "extracted", "included_in_synthesis", "cited_in_report")


def test_abstract_only_and_missing_text_are_different_stages():
    """Both mean 'we could not read the results', but only one of them yielded
    a document — conflating them misstates the corpus size."""
    state = _state()
    nodes._exclude(state, "P1", "abstract_only", "no PDF")
    nodes._exclude(state, "P2", "no_text_available", "no PDF and no abstract")
    assert set(state["exclusion_counts"]) == {"abstract_only", "no_text_available"}
