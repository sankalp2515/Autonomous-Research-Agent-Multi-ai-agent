"""Discovery map: a similarity graph over the corpus's papers.

Each paper becomes a node; edges connect papers whose content is semantically
close (cosine over a title + opening-chunk embedding). This is the
ResearchRabbit-style map done with *real* relationships from data we already
have — and every node is actionable in the UI (ask it, find similar, add
neighbours). No extra API calls; runs on local embeddings.
"""

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Chunk, Document
from app.ml.local_models import embed_texts

logger = get_logger("map")

NEIGHBORS = 4          # edges drawn per node (to its closest papers)
SIM_THRESHOLD = 0.55   # minimum cosine to draw an edge

# Layout canvas — positions are precomputed HERE (server-side, then cached) so
# the browser never re-runs an O(n²) force simulation on every mount. The map
# opens instantly; the frontend only reads x/y and animates entrance.
_W, _H = 920.0, 580.0


def _clusters(node_ids: list[str], edges: list[dict]) -> dict[str, int]:
    """Union-find over edges → a community id per node. This is what gives the
    map its MEANING: nodes sharing a colour are a sub-community of related work,
    so a researcher can see clusters, bridges between them, and outliers."""
    parent = {i: i for i in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        a, b = e.get("src"), e.get("dst")
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    roots: dict[str, int] = {}
    out: dict[str, int] = {}
    for i in node_ids:
        r = find(i)
        if r not in roots:
            roots[r] = len(roots)
        out[i] = roots[r]
    return out


def _layout(node_ids: list[str], edges: list[dict]) -> dict[str, tuple[float, float]]:
    """Deterministic Fruchterman-Reingold force layout, computed once server-side.
    Seeded on a circle (deterministic) so the same corpus always maps the same."""
    n = len(node_ids)
    pos = {
        nid: [
            _W / 2 + math.cos(i / max(n, 1) * math.tau) * 180 + (i % 7),
            _H / 2 + math.sin(i / max(n, 1) * math.tau) * 150 + (i % 5),
        ]
        for i, nid in enumerate(node_ids)
    }
    if n < 2:
        return {nid: (p[0], p[1]) for nid, p in pos.items()}
    adj = [(e["src"], e["dst"], float(e.get("weight", 0.5))) for e in edges
           if e.get("src") in pos and e.get("dst") in pos]
    k = math.sqrt((_W * _H) / n) * 0.55
    for it in range(260):
        disp = {nid: [0.0, 0.0] for nid in node_ids}
        for a in range(n):
            for b in range(a + 1, n):
                ia, ib = node_ids[a], node_ids[b]
                pa, pb = pos[ia], pos[ib]
                dx, dy = pa[0] - pb[0], pa[1] - pb[1]
                d = math.hypot(dx, dy) or 0.01
                f = (k * k) / d
                ux, uy = dx / d, dy / d
                disp[ia][0] += ux * f
                disp[ia][1] += uy * f
                disp[ib][0] -= ux * f
                disp[ib][1] -= uy * f
        for src, dst, w in adj:
            pa, pb = pos[src], pos[dst]
            dx, dy = pa[0] - pb[0], pa[1] - pb[1]
            d = math.hypot(dx, dy) or 0.01
            f = ((d * d) / k) * (0.4 + w)
            ux, uy = dx / d, dy / d
            disp[src][0] -= ux * f
            disp[src][1] -= uy * f
            disp[dst][0] += ux * f
            disp[dst][1] += uy * f
        temp = (1 - it / 260) * (_W / 12)
        for nid in node_ids:
            dp = disp[nid]
            dl = math.hypot(dp[0], dp[1]) or 0.01
            p = pos[nid]
            p[0] = max(28, min(_W - 28, p[0] + (dp[0] / dl) * min(dl, temp)))
            p[1] = max(28, min(_H - 28, p[1] + (dp[1] / dl) * min(dl, temp)))
    return {nid: (round(p[0], 1), round(p[1], 1)) for nid, p in pos.items()}


def _finalize(nodes: list[dict], edges: list[dict]) -> dict:
    """Attach precomputed x/y and a cluster id to every node, so the client
    renders instantly. Number of distinct clusters is reported for the legend."""
    ids = [nd["id"] for nd in nodes]
    clusters = _clusters(ids, edges)
    pos = _layout(ids, edges)
    for nd in nodes:
        x, y = pos.get(nd["id"], (_W / 2, _H / 2))
        nd["x"], nd["y"] = x, y
        nd["cluster"] = clusters.get(nd["id"], 0)
    n_clusters = len(set(clusters.values())) if clusters else 0
    return {"nodes": nodes, "edges": edges, "clusters": n_clusters, "w": _W, "h": _H}


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
        return _finalize(nodes, [])

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
        return _finalize(nodes, [])

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
    # cite. TODO/disabled by default — the S2 references API is rate-limited
    # without a key and made the map hang; similarity edges (below) are local
    # and fast. Flip settings.map_citation_edges_enabled to re-enable.
    from app.core.config import get_settings
    if not get_settings().map_citation_edges_enabled:
        sim_edges = [{"src": a, "dst": b, "weight": round(w, 3), "kind": "similar"}
                     for (a, b), w in pair_w.items()]
        logger.info("map built (similarity only)",
                    extra={"project_id": project_id, "nodes": len(nodes),
                           "similar": len(sim_edges)})
        return _finalize(nodes, sim_edges)

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
    return _finalize(nodes, edges)
