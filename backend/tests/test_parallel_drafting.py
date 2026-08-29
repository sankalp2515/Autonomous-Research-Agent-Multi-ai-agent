"""Cross-section dedup after parallel drafting.

Drafting used to be a serial loop purely so each section could see what the
previous ones had shipped. That bookkeeping made the pipeline's second-largest
block un-parallelisable, so the dependency was removed: sections draft
concurrently and duplicates are resolved once, afterwards.

The property that must not regress is the one the serial loop provided — no
finding is restated across sections — plus one the serial loop never had:
"first" now means FIRST IN THE REPORT, not first to finish, so the result no
longer depends on scheduling.
"""

from app.agents.nodes import _dedupe_across_sections


def _section(heading, texts, status="verified"):
    return {
        "heading": heading,
        "status": status,
        "claim_ids": [f"{heading}-{i}" for i in range(len(texts))],
        "claim_texts": list(texts),
        "gap_note": "",
        "layout": None,
        "subthemes": [],
    }


def test_duplicate_is_dropped_from_the_later_section():
    state = {}
    a = _section("A", ["GraphRAG cuts latency by 40%.", "Indexing costs 7702s."])
    b = _section("B", ["Recall reaches 87.9%.", "GraphRAG cuts latency by 40%."])
    dropped = _dedupe_across_sections(state, [a, b])

    assert dropped == 1
    assert a["claim_texts"] == ["GraphRAG cuts latency by 40%.", "Indexing costs 7702s."]
    assert b["claim_texts"] == ["Recall reaches 87.9%."]           # duplicate removed
    assert len(b["claim_ids"]) == 1


def test_near_duplicates_are_caught_not_just_exact_ones():
    """Normalization strips case and punctuation, so a restatement that differs
    only cosmetically is still a restatement."""
    state = {}
    a = _section("A", ["GraphRAG cuts latency by 40%."])
    b = _section("B", ["graphrag cuts latency by 40%"])
    assert _dedupe_across_sections(state, [a, b]) == 1
    assert b["status"] == "gap"


def test_dedup_is_order_deterministic_not_completion_order():
    """The whole point of moving dedup out of the draft loop: the same outline
    must yield the same drops however the concurrent tasks happened to finish."""
    def run(sections):
        state = {}
        _dedupe_across_sections(state, sections)
        return [s["claim_texts"] for s in sections]

    first = run([_section("A", ["shared finding", "a-only"]),
                 _section("B", ["b-only", "shared finding"])])
    second = run([_section("A", ["shared finding", "a-only"]),
                  _section("B", ["b-only", "shared finding"])])
    assert first == second
    assert first == [["shared finding", "a-only"], ["b-only"]]


def test_section_emptied_by_dedup_becomes_an_honest_gap():
    state = {}
    a = _section("A", ["only finding"])
    b = _section("B", ["only finding"])
    _dedupe_across_sections(state, [a, b])

    assert b["status"] == "gap"
    assert b["claim_ids"] == []
    assert "already answered by findings in earlier sections" in b["gap_note"]


def test_layout_is_dropped_when_claims_are_removed():
    """A presentation layout indexes INTO the claim list, so a layout built
    before dedup would point at the wrong findings after it."""
    state = {}
    a = _section("A", ["shared"])
    b = _section("B", ["shared", "kept"])
    b["layout"] = {"kind": "table", "columns": ["x"], "rows": [{"label": "r", "cells": {"x": [0]}}]}
    b["subthemes"] = [{"heading": "h", "findings": [0, 1]}]

    _dedupe_across_sections(state, [a, b])

    assert b["claim_texts"] == ["kept"]
    assert b["layout"] is None
    assert b["subthemes"] == []


def test_layout_is_preserved_when_nothing_is_removed():
    state = {}
    a = _section("A", ["one"])
    b = _section("B", ["two"])
    layout = {"kind": "table", "columns": ["x"], "rows": []}
    b["layout"] = layout
    assert _dedupe_across_sections(state, [a, b]) == 0
    assert b["layout"] is layout


def test_gap_sections_are_left_alone():
    state = {}
    gap = _section("A", [], status="gap")
    gap["gap_note"] = "no relevant sources in corpus"
    b = _section("B", ["finding"])
    _dedupe_across_sections(state, [gap, b])

    assert gap["status"] == "gap"
    assert gap["gap_note"] == "no relevant sources in corpus"
    assert b["claim_texts"] == ["finding"]


def test_used_claim_texts_reflects_what_actually_shipped():
    state = {}
    a = _section("A", ["alpha"])
    b = _section("B", ["alpha", "beta"])
    _dedupe_across_sections(state, [a, b])
    assert sorted(state["used_claim_texts"]) == ["alpha", "beta"]
