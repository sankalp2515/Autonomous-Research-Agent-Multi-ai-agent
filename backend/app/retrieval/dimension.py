"""Dimension-directed evidence retrieval (P0-B).

THE BUG THIS FIXES. Per-paper extraction used to call the general retriever once
per paper with ONE generic string — the run objective — and keep the top 8 chunks
of a ~60-chunk paper. Every comparison axis the question needed (accuracy,
latency, token cost, limitations) had to be answered from whichever 8 chunks that
single query happened to rank, and a generic objective query ranks the abstract
and the introduction, not the efficiency table on page 7. Measured on a real run:
of 100 study x dimension cells, 38 were filled, and roughly half the empty ones
were empty despite the paper containing the evidence — e.g. 16 chunks mentioning
latency in a paper whose latency cell read as a silent study.

So the fix is NOT "raise top_k". Raising it globally spends context on more of the
same badly-targeted ranking. The fix is to ask the paper a SEPARATE, vocabulary-
rich question per dimension, and to spend the per-paper budget where the evidence
for that dimension actually is:

  1. one lexical (BM25) index per document, queried with the dimension's own
     terminology (name + synonyms + metrics + the entities under study);
  2. dense ANN scoped INSIDE the document (see qdrant_store.search document_ids —
     without that filter, doc-scoped dense retrieval was returning nothing);
  3. RRF fusion of every variant's ranking, exactly as the main retriever does;
  4. deterministic evidence priors — a QUANTITATIVE dimension prefers chunks that
     actually carry numbers and unit tokens, and any dimension prefers chunks
     whose SECTION matches where that axis is normally reported;
  5. optional cross-encoder rerank over the surviving candidates;
  6. an ADAPTIVE budget: a dimension the paper clearly measures earns more chunks
     than one it barely mentions, instead of a flat per-paper ceiling.

Everything here is retrieval-side: local models and Postgres, no LLM calls. It
changes WHAT EVIDENCE THE MODEL SEES, never what counts as verified — the
quote-match + NLI gate downstream is untouched.
"""

import math
import re
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Chunk, Document
from app.ml.local_models import embed_texts, rerank
from app.retrieval.hybrid import RetrievedChunk
from app.stores.qdrant_store import search as qdrant_search

logger = get_logger("retrieval.dimension")

_TOKEN = re.compile(r"[a-z0-9]+")

# A number that looks like a MEASUREMENT rather than a citation year or a section
# number: a figure optionally carrying a unit or sitting next to a metric word.
_NUMERIC = re.compile(
    r"\d[\d,]*\.?\d*\s?(?:%|ms\b|s\b|sec\b|seconds?\b|min\b|hours?\b|x\b|×|"
    r"gb\b|mb\b|kb\b|k\b|m\b|b\b|tokens?\b|usd\b|\$|qps\b|pp\b|points?\b)",
    re.IGNORECASE,
)
_ANY_NUMBER = re.compile(r"\d[\d,]*\.?\d*")
# Table-ish text: pymupdf4llm flattens tables into pipe/whitespace grids, and the
# numbers a comparison needs overwhelmingly live in them.
_TABLE_HINT = re.compile(r"\|.*\|", re.MULTILINE)


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class DimensionSpec:
    """Retrieval-side view of one EvidenceDimension.

    Deliberately a plain dataclass and not the pydantic model: this module is
    imported by the retriever, and the retriever must not depend on the agent
    schemas (import cycle) — nor should a retrieval test need an LLM schema.
    """
    name: str
    kind: str = "quantitative"
    description: str = ""
    synonyms: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    location_hints: list[str] = field(default_factory=list)

    @property
    def quantitative(self) -> bool:
        return self.kind == "quantitative"


@dataclass
class DimensionHits:
    """What one dimension's search actually looked at — the coverage record.

    This is the evidence behind a later 'not reported' verdict: how many distinct
    queries were run and how many passages were examined. Absence of evidence is
    only allowed to become evidence of absence when this record is substantial.
    """
    dimension: str
    queries: list[str]
    chunks: list[RetrievedChunk]
    examined: int = 0          # candidates scored, before the top-k cut
    best_score: float = 0.0    # strength of the top match (signal, not proof)


@dataclass
class DimensionQuery:
    """One angle on a dimension, with the weight it carries in fusion.

    Weights exist because the angles are not equally diagnostic. The axis's own
    terminology and its unit tokens are what distinguish a latency passage from
    a passage that merely contains the word 'retrieval'; the entity and
    objective angles add topical grounding but, left at equal weight, they let
    the corpus's dominant topic (accuracy, here) outvote the axis actually being
    searched for — which is precisely the failure this module exists to remove.
    """
    text: str
    weight: float = 1.0
    purpose: str = "terms"


def build_dimension_queries(dim: DimensionSpec, entities: list[str],
                            objective: str = "",
                            profile: dict | None = None) -> list[DimensionQuery]:
    """The retrieval vocabulary for one axis, as several complementary angles.

    They fail differently, which is the point:
      - TERMS: the axis and every phrasing the literature uses for it. Catches a
        paper that says "response time" where the question said "latency".
      - METRICS: the units/metric tokens. Catches a results table that never
        writes the word 'latency' at all, only 'ms'.
      - ENTITIES: the axis crossed with the systems under study. Catches the
        comparative sentence ("GraphRAG needs 9.03s vs 1.2s for vector search").
      - PROFILE: the axis crossed with THIS PAPER'S OWN vocabulary, read off its
        abstract at screening (Phase 1b). Every angle above is built from the
        RUN-LEVEL schema, so every paper was searched with identical words —
        but doc-scoped BM25 lives or dies on the terms the document actually
        uses. A paper that reports "EM on MuSiQue" is reachable by those two
        tokens and hard to reach by the question's generic phrasing.
      - OBJECTIVE: the run's general question, kept at LOW weight as topical
        ballast only. This is the query the old pipeline used for everything,
        and at full weight it drowns the axis-specific angles above.

    The profile is a PRIOR, never evidence: it only decides what we read, never
    what counts as verified, and an absent or wrong profile costs recall at
    worst — every other angle is still searched.

    Deterministic: sorted and deduped, so one dimension always searches the same
    way and two runs of a question stay comparable.
    """
    profile = profile or {}
    # The paper's own names for what it evaluates join the run's entities: this
    # is the angle that most directly benefits from the paper's own wording.
    paper_systems = [s for s in (profile.get("named_systems") or []) if s]
    all_entities = sorted({e for e in [*entities, *paper_systems] if e})

    terms = [dim.name, *sorted({s for s in dim.synonyms if s})]
    out: list[DimensionQuery] = [
        DimensionQuery(" ".join(terms[:8]).strip(), 1.0, "terms")]
    if dim.metrics:
        out.append(DimensionQuery(
            (dim.name + " " + " ".join(sorted(set(dim.metrics))[:8])).strip(),
            1.0, "metrics"))
    paper_vocab = (sorted({m for m in (profile.get("named_metrics") or []) if m})[:6]
                   + sorted({d for d in (profile.get("named_datasets") or []) if d})[:4])
    if paper_vocab:
        out.append(DimensionQuery(
            (dim.name + " " + " ".join(paper_vocab)).strip(), 0.8, "profile"))
    if all_entities:
        out.append(DimensionQuery(
            (dim.name + " " + " ".join(all_entities[:6])).strip(),
            0.5, "entities"))
    if objective:
        out.append(DimensionQuery(
            (dim.name + " " + objective).strip()[:300], 0.35, "objective"))
    deduped, seen = [], set()
    for q in out:
        text = " ".join(q.text.split())
        if text and text.lower() not in seen:
            seen.add(text.lower())
            deduped.append(DimensionQuery(text, q.weight, q.purpose))
    return deduped


def weighted_rrf(rankings: list[tuple[list[str], float]], k: int = 60) -> dict[str, float]:
    """Reciprocal-rank fusion that respects a per-ranking weight."""
    scores: dict[str, float] = {}
    for ranking, weight in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + weight / (k + rank + 1)
    return scores


def _evidence_prior(dim: DimensionSpec, chunk: Chunk) -> float:
    """Deterministic, LLM-free preference among comparably-relevant passages.

    A quantitative axis is answered by a passage that CONTAINS THE NUMBER; a
    passage that merely says the word 'latency' in the related-work section is
    not evidence. Section hints add the paper's own structure as a signal, which
    the flat chunk ranking previously ignored entirely.
    """
    text = chunk.text or ""
    score = 0.0
    if dim.quantitative:
        if _NUMERIC.search(text):
            score += 0.6
        elif _ANY_NUMBER.search(text):
            score += 0.2
        if _TABLE_HINT.search(text):
            score += 0.25
        low = text.lower()
        # Word-boundary matching: a bare unit like 's' or 'm' would
        # otherwise match inside almost every word in the passage.
        hits = sum(1 for m in dim.metrics if m and re.search(
            r'(?<![a-z0-9])' + re.escape(m.lower()) + r'(?![a-z0-9])', low))
        score += 0.12 * min(hits, 3)
    section = (chunk.section or "").lower()
    if section and any(h and h.lower() in section for h in dim.location_hints):
        score += 0.4
    low = text.lower()
    syn_hits = sum(1 for s in dim.synonyms if s and s.lower() in low)
    score += 0.08 * min(syn_hits, 4)
    return score


async def _load_document_chunks(session: AsyncSession, project_id: str,
                                doc_id: str) -> tuple[list[Chunk], str, bool]:
    rows = (await session.execute(
        select(Chunk).where(Chunk.project_id == project_id,
                            Chunk.document_id == doc_id)
        .order_by(Chunk.ordinal)
    )).scalars().all()
    meta = (await session.execute(
        select(Document.title, Document.abstract_only).where(Document.id == doc_id)
    )).first()
    title = (meta[0] if meta else "") or ""
    abstract_only = bool(meta[1]) if meta else False
    return list(rows), title, abstract_only


async def retrieve_by_dimension(
    session: AsyncSession,
    project_id: str,
    doc_id: str,
    dimensions: list[DimensionSpec],
    *,
    entities: list[str] | None = None,
    objective: str = "",
    profile: dict | None = None,
    per_dimension_k: int | None = None,
    max_chunks: int | None = None,
    use_rerank: bool | None = None,
) -> tuple[list[RetrievedChunk], dict[str, DimensionHits]]:
    """Read ONE paper with one search per required dimension.

    Returns (deduplicated chunk list for the prompt, per-dimension coverage).
    The chunk list is ordered so the strongest evidence for each dimension
    interleaves — a paper never spends its whole window on the axis that
    happened to match hardest, which is exactly how the old single-query pass
    lost latency and cost evidence to accuracy.
    """
    settings = get_settings()
    per_dimension_k = per_dimension_k or settings.evidence_chunks_per_dimension
    max_chunks = max_chunks or settings.evidence_max_chunks_per_paper
    if use_rerank is None:
        use_rerank = settings.evidence_dimension_rerank
    entities = entities or []
    profile = profile or {}

    # ALLOCATION PRIOR (Phase 2b). The abstract said which axes this paper
    # reports; those axes earn a DEEPER candidate row, so the round-robin below
    # has more to give them once every axis has taken its fair share. The prior
    # can only ADD depth — it never shortens another axis's row — so a wrong
    # profile costs a little wasted retrieval, never a starved dimension.
    likely = {d.strip().lower() for d in (profile.get("likely_dimensions") or []) if d}

    def _k_for(dim: DimensionSpec) -> int:
        if likely and dim.name.strip().lower() in likely:
            return per_dimension_k + settings.evidence_profile_bonus_k
        return per_dimension_k

    # Within one depth of the rotation, axes the abstract flagged go first, so
    # that when the window truncates mid-depth it truncates on an axis the paper
    # probably does not report. Order is otherwise stable.
    dimensions = sorted(
        dimensions,
        key=lambda d: 0 if d.name.strip().lower() in likely else 1)

    chunks, title, abstract_only = await _load_document_chunks(session, project_id, doc_id)
    if not chunks:
        return [], {}
    by_id = {c.id: c for c in chunks}
    ids = list(by_id.keys())

    # One lexical index per document. Titles+sections are folded in (contextual
    # retrieval) so a chunk is matchable by the section it belongs to.
    bm25 = BM25Okapi([
        _tokenize(f"{title} {by_id[cid].section} {by_id[cid].text}") for cid in ids
    ])

    # One embedding batch for the whole paper's dimension queries — the model
    # server is lock-serialized, so batching here is the difference between a few
    # encodes and dozens of round trips per paper.
    all_queries: dict[str, list[DimensionQuery]] = {
        d.name: build_dimension_queries(d, entities, objective, profile)
        for d in dimensions
    }
    flat = [q.text for qs in all_queries.values() for q in qs]
    vectors: list[list[float]] = []
    if flat:
        try:
            vectors = await embed_texts(flat)
        except Exception:
            logger.info("dimension dense retrieval unavailable; lexical only")
            vectors = []
    vec_of = {q: v for q, v in zip(flat, vectors)} if vectors else {}

    coverage: dict[str, DimensionHits] = {}
    picks: dict[str, list[str]] = {}

    for dim in dimensions:
        queries = all_queries[dim.name]
        rankings: list[tuple[list[str], float]] = []
        for q in queries:
            scores = bm25.get_scores(_tokenize(q.text))
            rankings.append(([cid for _, cid in sorted(
                zip(scores, ids), key=lambda t: t[0], reverse=True)][:20], q.weight))
            vec = vec_of.get(q.text)
            if vec is not None:
                try:
                    hits = await qdrant_search(vec, project_id, limit=20,
                                               document_ids=[doc_id])
                    dense = [cid for cid, _ in hits if cid in by_id]
                    if dense:
                        rankings.append((dense, q.weight))
                except Exception:
                    logger.info("dimension dense search failed; lexical only")

        fused = weighted_rrf([r for r in rankings if r[0]], k=settings.rrf_k)
        if not fused:
            coverage[dim.name] = DimensionHits(
                dim.name, [q.text for q in queries], [], 0, 0.0)
            continue

        # Deterministic evidence prior on top of the fused relevance order,
        # sized to be worth roughly one rank position at the head of the list:
        # enough that the passage carrying the actual measurement outranks a
        # passage that merely shares vocabulary with it, not so much that it
        # overrides relevance outright.
        dim_k = _k_for(dim)
        scored = {cid: fused[cid] + 0.02 * _evidence_prior(dim, by_id[cid])
                  for cid in fused}
        candidates = sorted(scored, key=scored.get, reverse=True)[:max(dim_k * 3, 12)]

        if use_rerank and len(candidates) > dim_k:
            try:
                ce = await rerank(queries[0].text,
                                  [by_id[cid].text for cid in candidates])
                candidates = [cid for _, cid in sorted(
                    ((s + _evidence_prior(dim, by_id[cid]), cid)
                     for s, cid in zip(ce, candidates)),
                    key=lambda t: t[0], reverse=True)]
            except Exception:
                logger.info("dimension rerank skipped; fused order kept")

        top = candidates[:dim_k]
        picks[dim.name] = top
        coverage[dim.name] = DimensionHits(
            dimension=dim.name, queries=[q.text for q in queries], chunks=[],
            examined=len(candidates),
            best_score=round(max((scored[c] for c in top), default=0.0), 5),
        )

    # ADAPTIVE ALLOCATION. Round-robin across dimensions rather than
    # concatenating them: with a flat cut, the first dimension in the list would
    # eat the paper's whole window and the last would get nothing — reproducing
    # the very starvation this module exists to remove. A dimension with no
    # candidates simply drops out of the rotation, so its share flows to the
    # dimensions that do have evidence (this IS the adaptive budget: 3 chunks for
    # a thin axis, 15 for a rich one, without a per-axis quota).
    ordered: list[str] = []
    seen: set[str] = set()
    depth = 0
    while len(ordered) < max_chunks:
        progressed = False
        for dim in dimensions:
            row = picks.get(dim.name) or []
            if depth < len(row):
                progressed = True
                cid = row[depth]
                if cid not in seen:
                    seen.add(cid)
                    ordered.append(cid)
                    if len(ordered) >= max_chunks:
                        break
        if not progressed:
            break
        depth += 1

    out: list[RetrievedChunk] = []
    for cid in ordered:
        c = by_id[cid]
        out.append(RetrievedChunk(
            chunk_id=c.id, document_id=c.document_id, document_title=title,
            section=c.section, page_start=c.page_start, page_end=c.page_end,
            text=c.text, score=0.0, abstract_only=abstract_only,
            source_type="paper",
        ))
    picked = {c.chunk_id for c in out}
    for name, hits in coverage.items():
        hits.chunks = [c for c in out if c.chunk_id in set(picks.get(name, [])) & picked]

    logger.info("dimension retrieval", extra={
        "doc": doc_id, "chunks_in_doc": len(ids), "dimensions": len(dimensions),
        "returned": len(out),
        "per_dim": {k: len(v.chunks) for k, v in coverage.items()}})
    return out, coverage


def coverage_is_sufficient(hits: DimensionHits | None, *, full_text: bool,
                           min_queries: int = 2, min_chunks: int = 4) -> bool:
    """Was the search thorough enough that silence MEANS something?

    This is the epistemic hinge of the whole rework. 'Not reported' is a claim
    ABOUT THE PAPER; we may only make it when we actually looked hard enough for
    the absence to be informative. An abstract-only document can never satisfy
    it — we never had the paper's results at all — and neither can a dimension
    whose search surfaced almost nothing to read. Everything failing this test is
    reported as extraction_uncertain, which is a claim about VERISCOPE, not about
    the study.
    """
    if not full_text or hits is None:
        return False
    return len(hits.queries) >= min_queries and hits.examined >= min_chunks


def numeric_density(text: str) -> float:
    """Fraction of a passage that looks like measurement — used by the benchmark
    to decide whether a missing cell was RECOVERABLE from the corpus."""
    if not text:
        return 0.0
    return min(1.0, len(_NUMERIC.findall(text)) / max(1.0, math.log1p(len(text))))
