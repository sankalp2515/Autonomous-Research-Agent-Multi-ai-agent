"""Interactive pre-run screening.

Searches arXiv + Semantic Scholar, ranks by authority, and returns EVERY
candidate with a keep/drop recommendation + a plain reason — WITHOUT ingesting
anything. The researcher then approves exactly what enters the corpus
(human-in-the-loop). This is the transparent "why these sources?" surface: the
full funnel is visible, and the researcher, not a hidden cap, decides.

Screening on title+abstract BEFORE download is deliberate: downloading and
parsing dozens of PDFs is the expensive step (~30-45s each), so we let the
researcher cut the set down first.
"""

import asyncio
import re

from app.agents import sources
from app.agents.schemas import Clarification, ScreeningResult
from app.core.logging import get_logger
from app.agents.nodes import _SCHEMA_SYSTEM
from app.llm.router import complete_json

logger = get_logger("screening")

_CLARIFY_PROMPT = (
    "Derive the academic FIELD, the user's objective, 3-5 sub-questions, and any "
    "CONSTRAINTS stated anywhere (a range '2024-2026' -> since_year=2024, "
    "until_year=2026; 'after 2022' -> since_year=2022; 'before 2020' -> "
    "until_year=2020; 'at least 50 citations' -> min_citations=50; else 0). Set "
    "in_scope=false when the question is really biomedicine, neuroscience, "
    "psychology, social science, humanities, medicine or law — this platform "
    "searches arXiv + Semantic Scholar for computer-science / engineering research."
)




# ── axis coverage, before anything is ingested ───────────────────────────
#
# The expensive failure is not a bad paper — it is discovering, forty minutes
# and twenty-six PDFs later, that the corpus was never going to answer one of
# the axes the question needs. That is what produced a five-study review whose
# every axis came back "no comparable evidence".
#
# So the probe estimates, per required axis, how many screened-in candidates
# even MENTION it — matching the axis's own retrieval vocabulary against
# title+abstract. It is deliberately a keyword count and nothing cleverer:
#
#   * it is free (no LLM call, no downloads), so it can run before the commit;
#   * an abstract that never uses the word is very unlikely to carry the
#     measurement, so the count is a fair UPPER bound on what extraction can
#     find; and
#   * it is honest about being an upper bound — a mention is not a measurement,
#     and the wording says so.
#
# A researcher seeing "cost: 2 of 34 candidates mention it" can widen the query,
# drop the axis, or accept the gap knowingly — all of which are better than
# finding out at the end.

def _axis_terms(dim: dict) -> list[str]:
    """Every phrasing that would count as this axis being discussed."""
    terms = [dim.get("name", "")]
    terms += list(dim.get("synonyms") or [])
    terms += list(dim.get("metrics") or [])
    out, seen = [], set()
    for t in terms:
        t = " ".join((t or "").split()).strip().lower()
        # Single characters ("s", "%", "x") match nearly everything and would
        # report every axis as covered. Two-character tokens are KEPT, because
        # they include the most common metric names there are — f1, em, ms —
        # and dropping them made an axis measured by every paper read as
        # "barely present". Word-boundary matching (below) is what makes them
        # safe: "ms" must not fire on "terms".
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _axis_pattern(terms: list[str]) -> re.Pattern | None:
    """Word-boundary alternation over the axis vocabulary.

    Substring matching was the other half of the bug: it makes short metric
    tokens unusable and quietly inflates longer ones ("cost" inside "costly" is
    fine; "ms" inside "systems" is not).
    """
    if not terms:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b")


def axis_coverage(candidates: list[dict], schema: dict) -> list[dict]:
    """Per required axis: how many kept candidates mention it at all."""
    dims = list((schema or {}).get("required_dimensions") or [])
    if not dims:
        return []
    kept = [c for c in candidates if c.get("recommend") == "keep"]
    haystacks = [f"{c.get('title', '')} {c.get('abstract', '')}".lower() for c in kept]

    rows = []
    for dim in dims:
        terms = _axis_terms(dim)
        pattern = _axis_pattern(terms)
        n = sum(1 for text in haystacks if pattern and pattern.search(text))
        share = round(n / len(kept), 3) if kept else 0.0
        rows.append({
            "axis": dim.get("name", ""),
            "candidates_mentioning": n,
            "candidates_kept": len(kept),
            "share": share,
            # Named thresholds rather than a score: the reader is deciding
            # whether to spend 40 minutes, not grading the corpus.
            "verdict": ("well covered" if share >= 0.5 else
                        "thin" if share >= 0.15 else "barely present"),
            "terms": terms[:8],
        })
    rows.sort(key=lambda r: r["candidates_mentioning"])
    return rows


async def screen_candidates(query: str, since_year: int = 0, until_year: int = 0,
                            min_citations: int = 0, max_candidates: int = 40) -> dict:
    clar = await complete_json("clarify", f"Research request: {query}\n{_CLARIFY_PROMPT}", Clarification)

    # Constraints: caller (UI chips) is authoritative; parsed values are a
    # backstop; always keep the tighter bound.
    sy = max(since_year or 0, clar.since_year or 0)
    bounds = [y for y in (until_year or 0, clar.until_year or 0) if y]
    uy = min(bounds) if bounds else 0
    mc = max(min_citations or 0, clar.min_citations or 0)
    since, until = sy or None, uy or None

    qs = [q for q in ([clar.objective] + list(clar.sub_questions or [])) if q][:5]
    results = await asyncio.gather(
        *[sources.search_arxiv(q, since_year=since, until_year=until) for q in qs],
        *[sources.search_semantic_scholar(q, since_year=since, until_year=until) for q in qs],
        return_exceptions=True,
    )
    hits: list[sources.PaperHit] = []
    for r in results:
        if not isinstance(r, Exception):
            hits.extend(r)

    best: dict[str, sources.PaperHit] = {}
    for h in hits:
        key = (h.arxiv_id or h.doi or h.title.lower().strip())[:120]
        if not key:
            continue
        prev = best.get(key)
        if prev is None or (h.citation_count or 0) > (prev.citation_count or 0):
            best[key] = h
    unique = sorted(best.values(), key=lambda h: (h.citation_count or 0, h.year or 0), reverse=True)[:max_candidates]

    # Relevance screen (best-effort).
    rel: dict[int, tuple[bool, float, str]] = {}
    if unique:
        numbered = "\n".join(
            f"[{i}] ({h.citation_count or 0} cites, {h.year or 'n.d.'}) {h.title} — {(h.abstract or '')[:280]}"
            for i, h in enumerate(unique)
        )
        try:
            res = await complete_json(
                "screen",
                f"Objective: {clar.objective}\nField: {clar.field}\n\nCandidates:\n{numbered}\n\n"
                "For EACH, decide if it is genuinely relevant to the objective and in the "
                "right field — reject keyword-only, off-subject matches. 0-1 score + one-line reason.",
                ScreeningResult,
            )
            for p in res.papers:
                if 0 <= p.index < len(unique):
                    rel[p.index] = (p.relevant, p.score, p.reason)
        except Exception:
            logger.info("screen relevance step skipped")

    candidates = []
    for i, h in enumerate(unique):
        is_rel, score, why = rel.get(i, (True, 0.5, ""))
        recommend, reason = "keep", (why or "relevant to the objective")
        if sy and h.year and h.year < sy or (uy and h.year and h.year > uy):
            recommend, reason = "drop", f"published {h.year} — outside the {sy or 'any'}–{uy or 'now'} window"
        elif mc and h.citation_count and h.citation_count < mc:
            recommend, reason = "drop", f"only {h.citation_count} citations — below the {mc} minimum"
        elif not is_rel or score < 0.5:
            recommend, reason = "drop", (why or "shares keywords but is off-subject")
        candidates.append({
            "source": h.source, "external_id": h.external_id, "title": h.title,
            "abstract": (h.abstract or "")[:600], "authors": h.authors, "year": h.year,
            "url": h.url, "pdf_url": h.pdf_url, "doi": h.doi, "arxiv_id": h.arxiv_id,
            "citation_count": h.citation_count, "venue": h.venue,
            "score": round(float(score), 2), "recommend": recommend, "reason": reason,
            "domain_fit": clar.field,
        })

    # The evidence schema this question requires, derived here so the
    # researcher sees the axes AND how well the candidate pool covers them
    # before committing to a run. Temperature 0 and idempotent, so the run
    # re-derives the same schema — the probe never changes what gets extracted.
    schema: dict = {}
    coverage: list[dict] = []
    try:
        from app.agents.schemas import ResearchEvidenceSchema
        schema_res = await complete_json(
            "structure",
            f"Research question: {query}\nObjective: {clar.objective}\n"
            f"Domain: {clar.domain or clar.field}\n\n"
            "Design the evidence schema this question requires.",
            ResearchEvidenceSchema, system=_SCHEMA_SYSTEM, temperature=0.0,
        )
        schema = schema_res.normalized().model_dump()
        coverage = axis_coverage(candidates, schema)
    except Exception:
        # Non-fatal: without it the screen still shows every candidate, just
        # without the per-axis warning.
        logger.info("axis coverage estimate skipped")

    return {
        "objective": clar.objective, "field": clar.field, "in_scope": clar.in_scope,
        "since_year": sy, "until_year": uy, "min_citations": mc,
        "found": len(hits), "candidates": candidates,
        "screening_criteria": (schema.get("screening_criteria") or []) if schema else [],
        "axis_coverage": coverage,
    }
