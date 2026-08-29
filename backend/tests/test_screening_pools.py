"""Regression test for the corpus-poisoning screening bug (Phase 0).

`search_arxiv` never populates citation_count — arXiv exposes none. The old
`_screen_papers` sorted ALL hits by citation_count descending and screened only
the top 24, so every arXiv paper sorted to 0 and fell off the end of the
screening window. For any question whose primary literature lives on arXiv
(most of current CS), the canonical papers were discarded before the screen ever
saw them.

These tests pin the fix: arXiv candidates must reach the screening head even
when Semantic Scholar returns a large, well-cited pool.
"""

import pytest

from app.agents import nodes
from app.agents.sources import PaperHit


def _hit(source: str, title: str, cites: int = 0, year: int = 2026) -> PaperHit:
    return PaperHit(
        source=source, external_id=title, title=title,
        abstract=f"abstract of {title}", year=year, citation_count=cites,
    )


@pytest.fixture
def state():
    return {"run_id": "r", "project_id": "p", "llm_calls_used": 0,
            "started_at": __import__("time").time(), "coverage_notes": []}


async def test_arxiv_papers_reach_the_screening_head(state, monkeypatch):
    """40 heavily-cited S2 records must not push arXiv out of the window."""
    seen_titles: list[str] = []

    async def fake_complete_json(_kind, prompt, _schema, **_kw):
        # Capture exactly which candidates the screen was shown.
        seen_titles.append(prompt)
        from app.agents.schemas import ScreenedPaper, ScreeningResult
        n = prompt.count("\n[") + prompt.count("[0]")
        return ScreeningResult(papers=[
            ScreenedPaper(index=i, relevant=True, reason="ok", score=0.9)
            for i in range(max(n, 1))
        ])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    s2 = [_hit("semantic_scholar", f"s2-paper-{i}", cites=500 - i) for i in range(40)]
    arxiv = [_hit("arxiv", f"arxiv-canonical-{i}", cites=0) for i in range(10)]

    await nodes._screen_papers(state, s2 + arxiv, "objective", "cs", 0)

    # Screening is batched, so "reached the screen" means "appeared in SOME
    # batch" — every candidate is screened now, not just the first window.
    prompt = "\n".join(seen_titles)
    shown = [t for t in (f"arxiv-canonical-{i}" for i in range(10)) if t in prompt]
    assert len(shown) == 10, (
        f"only {len(shown)}/10 arXiv papers reached the screen — they are being "
        "sorted out by citation_count again"
    )


async def test_interleave_alternates_pools(state, monkeypatch):
    """The head must not be one source's pool followed by the other's."""
    captured = {}

    async def fake_complete_json(_kind, prompt, _schema, **_kw):
        captured["prompt"] = prompt
        from app.agents.schemas import ScreenedPaper, ScreeningResult
        return ScreeningResult(papers=[
            ScreenedPaper(index=0, relevant=True, reason="ok", score=0.9)])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    s2 = [_hit("semantic_scholar", f"s2-{i}", cites=100 - i) for i in range(5)]
    arxiv = [_hit("arxiv", f"ax-{i}") for i in range(5)]
    await nodes._screen_papers(state, s2 + arxiv, "objective", "cs", 0)

    lines = [ln for ln in captured["prompt"].splitlines() if ln.startswith("[")]
    # Round-robin: arXiv pool leads, then the two alternate.
    assert "ax-0" in lines[0] and "s2-0" in lines[1], lines[:4]


async def test_citation_floor_still_keeps_unknown_counts(state, monkeypatch):
    """A citation floor must not silently delete arXiv (count unknown, not 0)."""
    async def fake_complete_json(_kind, prompt, _schema, **_kw):
        from app.agents.schemas import ScreenedPaper, ScreeningResult
        return ScreeningResult(papers=[
            ScreenedPaper(index=0, relevant=True, reason="ok", score=0.9)])

    monkeypatch.setattr(nodes, "complete_json", fake_complete_json)

    hits = [_hit("arxiv", "ax-unknown", cites=0),
            _hit("semantic_scholar", "s2-low", cites=3),
            _hit("semantic_scholar", "s2-high", cites=90)]
    out = await nodes._screen_papers(state, hits, "objective", "cs", 50)
    titles = {h.title for h in out}
    assert "ax-unknown" in titles     # unknown != below-floor
    assert "s2-low" not in titles     # genuinely below the floor
