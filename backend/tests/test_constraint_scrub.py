"""A constraint the user did not ask for must never be enforced.

FOUND LIVE, not hypothesized. Launching

    "Compare dense retrievers (DPR, ColBERT, SPLADE, BM25) on BEIR and MS MARCO:
     retrieval accuracy (nDCG@10, MRR@10), query latency, and index size"

the clarify step returned since_year=2023 and min_citations=50, and the UI
labelled both "parsed from your question · enforced". Neither is in that
sentence. A 50-citation floor removes essentially every recent arXiv preprint —
which for a retrieval question IS the literature — so the run would have been
built from an impoverished corpus while telling the user they had asked for it.

The guard is deliberately asymmetric: it can DROP a constraint the model
invented and can never ADD one. Ambiguity resolves toward "the user did not ask
for this", because an unrequested filter that quietly shrinks the corpus is far
worse than a missed one the user can simply restate.
"""

import pytest

from app.agents.constraints import scrub_constraints

LIVE_FAILURE = ("Compare dense retrievers (DPR, ColBERT, SPLADE, BM25) on BEIR "
                "and MS MARCO: retrieval accuracy (nDCG@10, MRR@10), query "
                "latency, and index size")


def test_the_live_failure_case_is_scrubbed():
    since, until, cites, dropped = scrub_constraints(
        LIVE_FAILURE, since_year=2023, until_year=0, min_citations=50)
    assert (since, until, cites) == (0, 0, 0)
    assert len(dropped) == 2
    assert any("citation" in d for d in dropped)


def test_numbers_in_metric_names_do_not_authorize_a_year_window():
    """'nDCG@10' and 'MRR@10' contain digits; none of them is a year."""
    since, _u, _c, _d = scrub_constraints("nDCG@10 and MRR@10 on BEIR",
                                          since_year=2010)
    assert since == 0


@pytest.mark.parametrize("query", [
    "GraphRAG papers with at least 50 citations",
    "only highly-cited work on retrieval",
    "compare RAG systems, cited 100+ times",
])
def test_a_real_citation_request_survives(query):
    _s, _u, cites, dropped = scrub_constraints(query, min_citations=50)
    assert cites == 50 and dropped == []


@pytest.mark.parametrize("query,since", [
    ("retrieval work after 2022", 2022),
    ("papers from the last two years on GraphRAG", 2024),
    ("recent advances in dense retrieval", 2023),
    ("state-of-the-art rerankers", 2024),
    ("2024-2026 agentic RAG", 2024),
])
def test_a_real_time_window_survives(query, since):
    got, _u, _c, dropped = scrub_constraints(query, since_year=since)
    assert got == since and dropped == []


def test_an_upper_bound_needs_a_cue_too():
    _s, until, _c, dropped = scrub_constraints("compare BM25 and ColBERT",
                                               until_year=2020)
    assert until == 0 and dropped


def test_an_impossible_window_is_dropped():
    since, until, _c, dropped = scrub_constraints(
        "work from 2024 to 2020", since_year=2024, until_year=2020)
    assert (since, until) == (0, 0)
    assert any("impossible" in d for d in dropped)


def test_the_guard_never_invents_a_constraint():
    """It may only ever subtract. A guard that could add one would be a second
    source of the very bug it exists to stop."""
    since, until, cites, dropped = scrub_constraints(
        "papers after 2022 with at least 10 citations")
    assert (since, until, cites) == (0, 0, 0) and dropped == []


def test_nothing_stated_and_nothing_parsed_is_silent():
    assert scrub_constraints("compare BM25 and ColBERT") == (0, 0, 0, [])


def test_dropped_notes_explain_the_consequence_not_just_the_action():
    """The note has to tell the reader why it mattered, or it reads as noise."""
    _s, _u, _c, dropped = scrub_constraints(LIVE_FAILURE, min_citations=50)
    assert "preprints" in dropped[0]
