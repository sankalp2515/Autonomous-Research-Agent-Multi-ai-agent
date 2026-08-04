"""Cross-session agent memory.

Closes the "no memory that persists/adapts across runs" gap: each project
accumulates episodic memories (summaries of past runs) and can recall them
semantically in later sessions. Recall uses the local embedding model when
available and degrades gracefully to keyword + recency otherwise.

Deliberately kept OUT of the verification path: memory is for orientation and
planning ("you researched X before"), never injected as answer evidence — the
grounding invariant (claims cite verified source spans, not memory) is intact.
"""

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Memory

logger = get_logger("memory")


# ── Pure ranking helpers (no DB / no ML — directly unit-tested) ──────────

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rank_by_embedding(query_emb: list[float], items: list[tuple[str, list[float] | None]],
                      k: int) -> list[tuple[str, float]]:
    """items: (text, embedding|None). Returns top-k (text, score) by cosine,
    ignoring items without an embedding."""
    scored = [(text, cosine(query_emb, emb)) for text, emb in items if emb]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]


def rank_by_keyword(query: str, texts: list[str], k: int) -> list[str]:
    """Fallback ranking: overlap of query terms (len>3), preserving input
    order (callers pass most-recent-first)."""
    terms = {t for t in query.lower().split() if len(t) > 3}
    if not terms:
        return texts[:k]
    scored = sorted(
        texts, key=lambda s: sum(t in s.lower() for t in terms), reverse=True
    )
    hits = [s for s in scored if any(t in s.lower() for t in terms)]
    return (hits or texts)[:k]


# ── Store (DB-backed) ────────────────────────────────────────────────────

async def _embed(text: str) -> list[float] | None:
    try:
        from app.ml.local_models import embed_texts
        vecs = await embed_texts([text])
        return vecs[0] if vecs else None
    except Exception:
        return None  # ML not installed / disabled -> keyword recall still works


async def remember(session: AsyncSession, project_id: str, kind: str, text: str,
                   *, source_ref: str = "", meta: dict | None = None) -> Memory:
    m = Memory(project_id=project_id, kind=kind, text=text.strip(),
               embedding=await _embed(text), source_ref=source_ref, meta=meta or {})
    session.add(m)
    await session.flush()
    return m


async def recall(session: AsyncSession, project_id: str, query: str, k: int = 5) -> list[dict]:
    rows = (await session.scalars(
        select(Memory).where(Memory.project_id == project_id)
        .order_by(Memory.created_at.desc())
    )).all()
    if not rows:
        return []
    by_text = {m.text: m for m in rows}
    q_emb = await _embed(query)
    if q_emb is not None:
        ranked = rank_by_embedding(q_emb, [(m.text, m.embedding) for m in rows], k)
        if ranked:
            return [_pack(by_text[t], score) for t, score in ranked]
    # Fallback: keyword over recency-ordered rows.
    texts = rank_by_keyword(query, [m.text for m in rows], k)
    return [_pack(by_text[t], 0.0) for t in texts]


def _pack(m: Memory, score: float) -> dict:
    return {"id": m.id, "kind": m.kind, "text": m.text, "source_ref": m.source_ref,
            "meta": m.meta, "score": round(score, 4),
            "created_at": m.created_at.isoformat()}


async def record_run(session: AsyncSession, project_id: str, *, title: str,
                     findings: list[str], gaps: list[str]) -> Memory:
    """Episodic memory of a completed run — a one-liner the project keeps."""
    text = f"Researched: {title}."
    if findings:
        text += " Covered: " + "; ".join(findings[:4]) + "."
    if gaps:
        text += " Open gaps: " + "; ".join(gaps[:2]) + "."
    return await remember(session, project_id, "episodic", text,
                          source_ref="run", meta={"title": title})
