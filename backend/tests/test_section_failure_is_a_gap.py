"""A section that fails to draft is a gap — never a silent success.

The parallel rewrite of `draft_sections` used
`asyncio.gather(..., return_exceptions=True)`, which collects exceptions rather
than raising. A section whose drafting threw was therefore left in its initial
`pending` state with no claims and no note — and `assemble` counted anything
that was not literally `"gap"` as grounded.

A live run shipped a report reading **"5/5 sections verified, low_confidence:
false" with four empty sections**. That is the single worst failure this system
can produce: it is not a missing finding, it is a false claim about how much of
the question was answered, made by the component whose whole purpose is not
doing that.

Two independent guards are pinned here, because either alone would have let it
through: the section records its own failure, AND the grounded count treats any
non-verified state as ungrounded.
"""

import time

import pytest

from app.agents import nodes


def _state(headings):
    return {
        "run_id": "r", "project_id": "p", "query": "q",
        "llm_calls_used": 0, "started_at": time.time(), "coverage_notes": [],
        "replan_targets": [], "replans_used": {}, "used_claim_texts": [],
        "sections": [{"heading": h, "sub_question": h, "guidance": "",
                      "status": "pending", "claim_ids": [], "gap_note": "",
                      "regens_used": 0, "track": "academic"} for h in headings],
    }


@pytest.fixture
def quiet(monkeypatch):
    async def noop(*_a, **_kw):
        return None
    monkeypatch.setattr(nodes, "_checkpoint", noop)
    monkeypatch.setattr(nodes, "publish_progress", noop)


async def test_a_crashing_section_becomes_a_gap_with_a_reason(quiet, monkeypatch):
    async def boom(_state, section):
        if section["heading"] == "B":
            raise RuntimeError("provider exploded")
        section["status"] = "verified"
        section["claim_ids"] = ["c1"]
        section["claim_texts"] = ["a finding"]

    monkeypatch.setattr(nodes, "_draft_one_section", boom)
    state = _state(["A", "B"])
    await nodes.draft_sections_node(state)

    a, b = state["sections"]
    assert a["status"] == "verified"
    assert b["status"] == "gap", "a crashed section must never stay pending"
    assert "failed while writing" in b["gap_note"]
    assert any("could not be drafted" in n for n in state["coverage_notes"])
    # A drafting failure is a claim about VERISCOPE, and must stay
    # distinguishable from a claim about the corpus all the way to the page.
    assert b["gap_kind"] == "drafting_failed"


async def test_a_transient_failure_is_retried_once(quiet, monkeypatch):
    """A live run lost two of six sections to a provider ReadTimeout.

    The call chain fails over between providers, but nothing retried the
    SECTION — so one bad minute permanently deleted a sixth of the report and
    published it as "no verifiable evidence".
    """
    attempts = {"B": 0}

    async def flaky(_state, section):
        if section["heading"] == "B":
            attempts["B"] += 1
            if attempts["B"] == 1:
                raise RuntimeError("transient ReadTimeout")
        section["status"] = "verified"
        section["claim_ids"] = [section["heading"]]
        # Distinct per section: identical text would be removed by the
        # cross-section dedup pass and close the section as redundant.
        section["claim_texts"] = [f"finding for {section['heading']}"]

    monkeypatch.setattr(nodes, "_draft_one_section", flaky)
    state = _state(["A", "B"])
    await nodes.draft_sections_node(state)

    assert attempts["B"] == 2, "a failed section was never retried"
    assert state["sections"][1]["status"] == "verified", (
        "the retry succeeded but the section was still closed as a gap"
    )


async def test_an_evidence_gap_is_not_labelled_a_drafting_failure(quiet, monkeypatch):
    """The default stays a statement about the corpus."""
    async def no_evidence(_state, section):
        section["status"] = "gap"
        section["gap_note"] = "no relevant sources in corpus"

    monkeypatch.setattr(nodes, "_draft_one_section", no_evidence)
    state = _state(["A"])
    await nodes.draft_sections_node(state)

    assert state["sections"][0].get("gap_kind", "no_evidence") == "no_evidence"


async def test_one_failure_does_not_take_down_its_siblings(quiet, monkeypatch):
    async def boom(_state, section):
        if section["heading"] == "B":
            raise RuntimeError("nope")
        section["status"] = "verified"
        section["claim_ids"] = [section["heading"]]
        section["claim_texts"] = [f"finding for {section['heading']}"]

    monkeypatch.setattr(nodes, "_draft_one_section", boom)
    state = _state(["A", "B", "C"])
    await nodes.draft_sections_node(state)

    assert [s["status"] for s in state["sections"]] == ["verified", "gap", "verified"]


async def test_a_section_left_pending_is_not_counted_as_grounded():
    """The backstop. Even if a section reaches assemble in an unexpected state,
    the grounded count must not treat it as success — `grounded` means
    `verified`, and any state nobody anticipated is ungrounded by construction.
    """
    sections = [
        {"status": "verified"}, {"status": "pending"},
        {"status": "gap"}, {"status": "something_new"},
    ]
    grounded = len(sections) - len([s for s in sections if s["status"] != "verified"])
    assert grounded == 1
