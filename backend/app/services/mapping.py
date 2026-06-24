"""Discovery map: a similarity graph over the corpus's papers.

Each paper becomes a node; edges connect papers whose content is semantically
close (cosine over a title + opening-chunk embedding). This is the
ResearchRabbit-style map done with *real* relationships from data we already
have — and every node is actionable in the UI (ask it, find similar, add
neighbours). No extra API calls; runs on local embeddings.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Chunk, Document
from app.ml.local_models import embed_texts

logger = get_logger("map")

NEIGHBORS = 4          # edges drawn per node (to its closest papers)
SIM_THRESHOLD = 0.55   # minimum cosine to draw an edge


async def build_map(session: AsyncSession, project_id: str) -> dict:
    docs = (await session.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.status == "indexed",
            Document.source_type.in_(["paper", "upload"]),
        )
    )).all()

    nodes = [{
        "id": d.id, "title": d.title, "year": d.year, "authors": d.authors,
        "source_type": d.source_type, "url": d.url, "arxiv_id": d.arxiv_id,
        "citations": int((d.meta or {}).get("citation_count") or 0),
        "abstract_only": d.abstract_only,
    } for d in docs]

    if len(docs) < 2:
        return {"nodes": nodes, "edges": []}

    texts = []
    for d in docs:
        first = await session.scalar(
            select(Chunk).where(Chunk.document_id == d.id).order_by(Chunk.ordinal).limit(1)
        )
        texts.append(f"{d.title}. {first.text[:300] if first else ''}")

    try:
        vecs = await embed_texts(texts)
    except Exception:
        logger.warning("map embedding failed; returning nodes only")
        return {"nodes": nodes, "edges": []}

    pair_w: dict[tuple[str, str], float] = {}
    n = len(docs)
    for i in range(n):
        sims = sorted(
            ((sum(a * b for a, b in zip(vecs[i], vecs[j])), j) for j in range(n) if j != i),
            reverse=True,
        )
        for s, j in sims[:NEIGHBORS]:
            if s >= SIM_THRESHOLD:
                a, b = sorted((docs[i].id, docs[j].id))
                pair_w[(a, b)] = max(pair_w.get((a, b), 0.0), float(s))

    # Citation edges (best-effort, directional): for papers with an S2-
    # resolvable id, fetch their references and link to corpus papers they
    # cite. Bounded + fail-soft so a slow/absent S2 never breaks the map.
    from app.agents.sources import fetch_references

    by_arxiv = {d.arxiv_id: d.id for d in docs if d.arxiv_id}
    by_doi = {(d.doi or "").lower(): d.id for d in docs if d.doi}
    cite_edges: list[dict] = []
    cite_pairs: set[tuple[str, str]] = set()
    fetched = 0
    for d in docs:
        if fetched >= 25:
            break
        sid = f"ARXIV:{d.arxiv_id}" if d.arxiv_id else (f"DOI:{d.doi}" if d.doi else None)
        if not sid:
            continue
        fetched += 1
        for ext in await fetch_references(sid):
            ax, di = ext.get("ArXiv"), (ext.get("DOI") or "").lower()
            tgt = by_arxiv.get(ax) if ax else None
            tgt = tgt or (by_doi.get(di) if di else None)
            if tgt and tgt != d.id:
                cite_edges.append({"src": d.id, "dst": tgt, "weight": 1.0, "kind": "cites"})
                cite_pairs.add(tuple(sorted((d.id, tgt))))

    sim_edges = [{"src": a, "dst": b, "weight": round(w, 3), "kind": "similar"}
                 for (a, b), w in pair_w.items() if (a, b) not in cite_pairs]
    edges = cite_edges + sim_edges
    logger.info("map built", extra={"project_id": project_id, "nodes": len(nodes),
                                    "cites": len(cite_edges), "similar": len(sim_edges)})
    return {"nodes": nodes, "edges": edges}
