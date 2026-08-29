"""Phase 1 — nothing unscreened may enter the corpus, and the screen profiles.

THE BUG THESE PIN. `_screen_papers` judged only the first `screen_max_candidates`
(50) of a 307-candidate pool and then returned

    [kept from head] + hits[screen_max_candidates:]

The comment claimed the tail was used "only as filler if the kept set is thinner
than the ingest cap", but nothing enforced that condition and nothing marked
those papers as unassessed. The ingest cap sliced them into the corpus, so an AI
alignment review shipped study rows for a paper on peripheral artery disease and
one on the Bhagavad Gita. Its own footer then reported "307 screened", when 50
had been.

The rule is now absolute: a paper reaches ingest only if a screening verdict
included it. A thin corpus is a true fact about the question; a padded one is a
false one.
"""

import time

import pytest

from app.agents import nodes
from app.agents.schemas import ScreenedPaper, ScreeningResult
from app.agents.sources import PaperHit


def _hit(source: str, title: str, cites: int = 0, year: int = 2026) -> PaperHit:
    return PaperHit(
        source=source, external_id=title, title=title,
        abstract=f"abstract of {title}", year=year, citation_count=cites,
    )


@pytest.fixture
def state():
    return {"run_id": "r", "project_id": "p", "llm_calls_used": 0,
            "started_at": time.time(), "coverage_notes": []}


def _keep_only(titles: set[str]):
    """Screen fake that includes exactly the candidates whose title is listed."""
    async def fake(_kind, prompt, _schema, **_kw):
        papers = []
        for line in prompt.splitlines():
            if not line.startswith("["):
                continue
            idx = int(line[1:line.index("]")])
            keep = any(t in line for t in titles)
            papers.append(ScreenedPaper(
                index=idx, relevant=keep, reason="ok" if keep else "off-topic",
                score=0.9 if keep else 0.1))
        return ScreeningResult(papers=papers)
    return fake


async def test_unscreened_tail_never_reaches_the_corpus(state, monkeypatch):
    """The regression itself: candidates past the screening cut are DROPPED."""
    monkeypatch.setattr(nodes, "complete_json", _keep_only({"good"}))
    # Force a cut far below the pool so there is a large tail to leak.
    monkeypatch.setattr(nodes.get_settings(), "screen_max_candidates", 10,
                        raising=False)

    hits = ([_hit("arxiv", f"good-{i}") for i in range(4)]
            + [_hit("arxiv", f"offtopic-{i}") for i in range(60)])
    out = await nodes._screen_papers(state, hits, "objective", "cs", 0)

    titles = {h.title for h in out}
    assert titles, "screening returned nothing at all"
    assert all(t.startswith("good") for t in titles), (
        f"unscreened papers reached the corpus: {sorted(titles)[:8]}"
    )


async def test_every_candidate_is_screened_not_just_the_first_window(state, monkeypatch):
    """A paper deep in the pool is still assessed on its merits."""
    monkeypatch.setattr(nodes, "complete_json", _keep_only({"needle"}))

    hits = ([_hit("semantic_scholar", f"filler-{i}", cites=100) for i in range(120)]
            + [_hit("arxiv", "needle-paper")])
    out = await nodes._screen_papers(state, hits, "objective", "cs", 0)

    assert {h.title for h in out} == {"needle-paper"}


async def test_funnel_screened_count_is_what_was_actually_screened(state, monkeypatch):
    """The footer says "N screened"; N must be papers a screen actually judged."""
    monkeypatch.setattr(nodes, "complete_json", _keep_only({"good"}))

    hits = [_hit("arxiv", "good-1")] + [_hit("arxiv", f"no-{i}") for i in range(75)]
    await nodes._screen_papers(state, hits, "objective", "cs", 0)

    funnel = state["funnel"]
    assert funnel["screened"] == 76
    assert funnel["screened_in"] == 1
    assert funnel["screened_out"] == 75


async def test_a_failed_batch_excludes_its_papers_rather_than_admitting_them(
        state, monkeypatch):
    """A provider error must not become an admission route."""
    async def flaky(_kind, prompt, _schema, **_kw):
        # Keyed on CONTENT, not call count: a batch is retried once, so a
        # count-based fake would be rescued by the retry and stop testing the
        # branch. This batch fails both attempts.
        if "batch1" in prompt:
            raise RuntimeError("provider exploded")
        return await _keep_only({"batch2"})(_kind, prompt, _schema)

    monkeypatch.setattr(nodes, "complete_json", flaky)
    monkeypatch.setattr(nodes.get_settings(), "screen_batch_size", 5, raising=False)
    monkeypatch.setattr(nodes.get_settings(), "screen_batch_concurrency", 1,
                        raising=False)

    hits = ([_hit("arxiv", f"batch1-{i}") for i in range(5)]
            + [_hit("arxiv", f"batch2-{i}") for i in range(5)])
    out = await nodes._screen_papers(state, hits, "objective", "cs", 0)

    titles = {h.title for h in out}
    assert not any(t.startswith("batch1") for t in titles), (
        "papers from the failed batch were admitted without ever being assessed"
    )
    assert any("could not be screened" in n for n in state["coverage_notes"])


async def test_total_screening_failure_is_recorded_not_silent(state, monkeypatch):
    """Falling back to authority order admits unscreened papers — say so."""
    async def boom(*_a, **_kw):
        raise RuntimeError("all providers down")

    monkeypatch.setattr(nodes, "complete_json", boom)

    hits = [_hit("arxiv", f"p-{i}") for i in range(6)]
    out = await nodes._screen_papers(state, hits, "objective", "cs", 0)

    assert len(out) == 6, "the run should not be sunk by a screening outage"
    assert state["funnel"]["screen_failed"] is True
    assert any("NOT assessed" in n for n in state["coverage_notes"])


async def test_profile_is_recorded_for_screened_papers(state, monkeypatch):
    """Phase 1b — the abstract's vocabulary survives the screen."""
    async def fake(_kind, prompt, _schema, **_kw):
        papers = []
        for line in prompt.splitlines():
            if not line.startswith("["):
                continue
            idx = int(line[1:line.index("]")])
            papers.append(ScreenedPaper(
                index=idx, relevant=True, reason="ok", score=0.9,
                likely_dimensions=["latency"], named_systems=["LightRAG"],
                named_datasets=["HotpotQA"], named_metrics=["F1"]))
        return ScreeningResult(papers=papers)

    monkeypatch.setattr(nodes, "complete_json", fake)

    hit = _hit("arxiv", "graph-paper")
    await nodes._screen_papers(state, [hit], "objective", "cs", 0)

    profile = state["screen_profiles"][nodes._hit_key(hit)]
    assert profile["named_datasets"] == ["HotpotQA"]
    assert profile["likely_dimensions"] == ["latency"]


async def test_full_abstract_reaches_the_screen(state, monkeypatch):
    """Abstracts were truncated to 300 chars — most of one sentence."""
    seen = {}

    async def fake(_kind, prompt, _schema, **_kw):
        seen["prompt"] = prompt
        return ScreeningResult(papers=[
            ScreenedPaper(index=0, relevant=True, reason="ok", score=0.9)])

    monkeypatch.setattr(nodes, "complete_json", fake)

    hit = _hit("arxiv", "long-paper")
    hit.abstract = "A" * 200 + "THE-RESULTS-SENTENCE" + "B" * 400
    await nodes._screen_papers(state, [hit], "objective", "cs", 0)

    assert "THE-RESULTS-SENTENCE" in seen["prompt"]


async def test_a_run_with_no_admitted_corpus_refuses(monkeypatch):
    """A run must never report from another question's papers.

    THE BUG THIS PINS. Retrieval is scoped to the PROJECT, not the run. A live
    run whose screen rejected 237 of 237 candidates ingested nothing, then
    drafted 21 verified claims citing 12 papers gathered for an EARLIER
    question — and shipped them under a funnel reading "0 studies included,
    ingested: 0". Every sentence was individually grounded and the document as a
    whole was false: the corpus it described was not the corpus it was written
    from. No gate catches that, because each claim really is faithful to its
    span.
    """
    state = {"run_id": "r", "project_id": "p", "query": "q",
             "llm_calls_used": 0, "started_at": time.time(),
             "coverage_notes": [], "plan": {"queries": {}}, "scope": "papers"}

    async def noop(*_a, **_kw):
        return None
    monkeypatch.setattr(nodes, "publish_progress", noop)
    # `_timed("research")` checkpoints to Postgres on entry and exit. Without
    # this the test passes or fails on whether a database happens to be running,
    # which is not what it is testing.
    monkeypatch.setattr(nodes, "_checkpoint", noop)

    async def no_papers(*_a, **_kw):
        return []
    monkeypatch.setattr(nodes.sources, "search_arxiv", no_papers)
    monkeypatch.setattr(nodes.sources, "search_semantic_scholar", no_papers)

    out = await nodes.research_node(state)

    assert out.get("rejected"), "an empty corpus must stop the run"
    assert "no corpus of its own" in out["rejected"]
    assert nodes.research_route(out) == "end"


def test_research_route_continues_when_a_corpus_exists():
    assert nodes.research_route({"paper_doc_ids": ["d1"]}) == "extract_evidence"
