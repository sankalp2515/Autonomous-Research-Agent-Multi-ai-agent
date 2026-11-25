"""Copy chunk vectors from Qdrant into chunks.embedding (pgvector).

    python scripts/backfill_pgvector.py                 # copy from Qdrant, re-embed the rest
    python scripts/backfill_pgvector.py --no-reembed    # copy only; report what is missing
    python scripts/backfill_pgvector.py --project <id>  # one project
    python scripts/backfill_pgvector.py --dry-run       # count only, write nothing

Inside the stack:
    docker compose --profile app exec worker python scripts/backfill_pgvector.py

Copies first (no model call: a vector read from Qdrant is byte-for-byte the
vector the corpus was indexed with), and re-embeds only what Qdrant does not
have. Resumable: it only ever touches chunks whose `embedding IS NULL`, and it
commits per batch, so an interrupted run continues where it stopped.

Exit code 0 only when every chunk of every indexed document has a vector, so
this can gate a cut-over in CI or a deploy script.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import text

BATCH = 256
_NOT_COLD = " AND COALESCE(d.meta->>'cold', 'false') <> 'true'"


def _point_id(chunk_id: str) -> str:
    # Must match app.stores.qdrant_store._point_id.
    return str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))


async def _pending(session, project: str | None, limit: int) -> list[tuple]:
    sql = ("SELECT c.id, c.section, c.text, d.title FROM chunks c "
           "JOIN documents d ON d.id = c.document_id "
           "WHERE c.embedding IS NULL AND d.status = 'indexed'"
           # Cold-tier documents were evicted on purpose; do not undo that.
           f"{_NOT_COLD}")
    params: dict = {"lim": limit}
    if project:
        sql += " AND c.project_id = :p"
        params["p"] = project
    sql += " ORDER BY c.id LIMIT :lim"
    return list((await session.execute(text(sql), params)).all())


async def _from_qdrant(chunk_ids: list[str]) -> dict[str, list[float]]:
    try:
        from app.core.config import get_settings
        from app.stores.qdrant_store import get_qdrant
        pts = await get_qdrant().retrieve(
            collection_name=get_settings().qdrant_collection,
            ids=[_point_id(c) for c in chunk_ids], with_vectors=True, with_payload=True)
    except Exception as exc:
        print(f"  qdrant unavailable ({str(exc)[:80]}); falling back to re-embed",
              file=sys.stderr)
        return {}
    out: dict[str, list[float]] = {}
    for p in pts:
        cid = (p.payload or {}).get("chunk_id")
        vec = p.vector
        if isinstance(vec, dict):  # named vectors: take the default/only one
            vec = next(iter(vec.values()), None)
        if cid and vec:
            out[cid] = list(vec)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project")
    ap.add_argument("--no-reembed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from app.db.session import session_scope
    from app.ingestion.pipeline import context_text
    from app.stores import pgvector_store

    async with session_scope() as s:
        await pgvector_store.ensure_ready(s)
        total = await s.scalar(text(
            "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE c.embedding IS NULL AND d.status = 'indexed'" + _NOT_COLD
            + (" AND c.project_id = :p" if args.project else "")),
            {"p": args.project} if args.project else {})
    print(f"chunks without a pgvector vector: {total}")
    if args.dry_run or not total:
        return 0 if not total else 1

    copied = reembedded = skipped = 0
    seen: set[str] = set()
    while True:
        async with session_scope() as s:
            rows = [r for r in await _pending(s, args.project, BATCH) if r[0] not in seen]
            if not rows:
                break
            ids = [r[0] for r in rows]
            seen.update(ids)
            found = await _from_qdrant(ids)
            missing = [r for r in rows if r[0] not in found]
            if missing and not args.no_reembed:
                from app.ml.local_models import embed_texts
                vecs = await embed_texts([context_text(t, sec, txt)
                                          for _, sec, txt, t in missing])
                for (cid, *_), v in zip(missing, vecs):
                    found[cid] = v
                reembedded += len(missing)
            else:
                skipped += len(missing)
            await pgvector_store.upsert_chunks(
                [(cid, vec, {}) for cid, vec in found.items()], session=s)
            copied += len(found) - (len(missing) if not args.no_reembed else 0)
        print(f"  {len(seen)}/{total}  copied={copied} re-embedded={reembedded} "
              f"skipped={skipped}")

    async with session_scope() as s:
        left = await s.scalar(text(
            "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE c.embedding IS NULL AND d.status = 'indexed'" + _NOT_COLD))
    print(f"done. copied={copied} re-embedded={reembedded} still-missing={left}")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
