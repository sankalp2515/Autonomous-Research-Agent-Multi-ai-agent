"""Resolve heterogeneous entity references into a grounding scope for one-off
chat contexts.

A user can select papers, verified claims, or prior answers ANYWHERE in the app
and build a throwaway chat context from them. Every ref is resolved down to real
documents + evidence chunks, so the resulting chat runs through the SAME
retrieval + verification gate as everything else — the ad-hoc context is
verifiable and transparent, not a free-text side channel. This is the
"living document" interaction, kept honest by construction.

Supported kinds (a paper, a claim, an answer cover map nodes, report claims,
chat claims, and prior Q&A — i.e. papers / questions / answers / claims):
  - "document" | "paper" | "upload" | "node" -> that document, scoped retrieval
  - "claim"                                   -> the claim's evidence chunks
                                                 (seeded) + its source document
  - "answer"                                  -> the union over the answer's
                                                 claims' chunks + documents
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Answer, Chunk, Claim, ClaimEvidence, Document
from app.retrieval.hybrid import RetrievedChunk

logger = get_logger("chatctx")

_DOC_KINDS = {"document", "paper", "upload", "node", "map_node"}


@dataclass
class ContextScope:
    document_ids: set[str] = field(default_factory=set)
    seed_chunk_ids: set[str] = field(default_factory=set)  # guaranteed-in-context
    labels: list[str] = field(default_factory=list)        # for UI transparency
    unknown: list[str] = field(default_factory=list)       # refs we couldn't resolve

    @property
    def empty(self) -> bool:
        return not self.document_ids and not self.seed_chunk_ids


async def _chunk_docs(session: AsyncSession, chunk_ids: set[str]) -> set[str]:
    if not chunk_ids:
        return set()
    rows = (await session.scalars(
        select(Chunk.document_id).where(Chunk.id.in_(chunk_ids))
    )).all()
    return {d for d in rows if d}


async def _add_claim(session: AsyncSession, project_id: str, claim_id: str, scope: ContextScope) -> None:
    claim = await session.get(Claim, claim_id)
    if claim is None or claim.project_id != project_id:
        scope.unknown.append(claim_id)
        return
    evs = (await session.scalars(
        select(ClaimEvidence.chunk_id).where(ClaimEvidence.claim_id == claim_id)
    )).all()
    scope.seed_chunk_ids.update(c for c in evs if c)
    scope.document_ids.update(await _chunk_docs(session, set(evs)))
    scope.labels.append(f"claim · {claim.text[:60].strip()}")


async def resolve_entities(
    session: AsyncSession, project_id: str, refs: list[dict]
) -> ContextScope:
    """refs: [{"kind": "...", "id": "..."}]. Order-independent; deduped."""
    scope = ContextScope()
    for ref in refs[:50]:  # bound the fan-out
        kind = (ref.get("kind") or "").lower()
        rid = ref.get("id") or ""
        if not rid:
            continue
        if kind in _DOC_KINDS:
            doc = await session.get(Document, rid)
            if doc is None or doc.project_id != project_id:
                scope.unknown.append(rid)
                continue
            scope.document_ids.add(rid)
            scope.labels.append(f"paper · {(doc.title or 'untitled')[:60].strip()}")
        elif kind == "claim":
            await _add_claim(session, project_id, rid, scope)
        elif kind == "answer":
            ans = await session.get(Answer, rid)
            if ans is None or ans.project_id != project_id:
                scope.unknown.append(rid)
                continue
            claim_ids = (await session.scalars(
                select(Claim.id).where(Claim.answer_id == rid)
            )).all()
            for cid in claim_ids:
                await _add_claim(session, project_id, cid, scope)
            scope.labels.append(f"answer · {ans.question[:60].strip()}")
        else:
            scope.unknown.append(rid)
    return scope


async def seed_chunks(session: AsyncSession, chunk_ids: set[str]) -> list[RetrievedChunk]:
    """Materialize selected-evidence chunks as retrieval hits so the exact
    passages a user picked are guaranteed to be in the drafting context (top
    score), not left to chance in the vector search."""
    if not chunk_ids:
        return []
    rows = (await session.execute(
        select(Chunk, Document.title, Document.abstract_only, Document.source_type)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_(chunk_ids))
    )).all()
    out: list[RetrievedChunk] = []
    for chunk, title, abstract_only, source_type in rows:
        out.append(RetrievedChunk(
            chunk_id=chunk.id, document_id=chunk.document_id,
            document_title=title or "", section=chunk.section,
            page_start=chunk.page_start, page_end=chunk.page_end,
            text=chunk.text, score=1.0,
            abstract_only=bool(abstract_only), source_type=source_type or "",
        ))
    return out
