"""The one entry point for dense vectors. Callers never import a backend.

VECTOR_BACKEND=pgvector (default) reads and writes chunks.embedding.
VECTOR_BACKEND=qdrant is the previous store, kept for exactly one release so a
bad cut-over is a config flip rather than a redeploy.

VECTOR_DUAL_WRITE=true additionally mirrors writes to the backend that is NOT
being read, so that flip stays instant during the migration window. A mirror
write failure is logged and counted, never raised: the primary write already
succeeded and the mirror is only a rollback aid.

Remove the qdrant branch (and qdrant-client) once a release has run on pgvector
with evals.evidence_bench recall at or above the Qdrant baseline.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.stores import pgvector_store

logger = get_logger("vectors")


def backend() -> str:
    return get_settings().vector_backend


def _mirror() -> str | None:
    s = get_settings()
    if not s.vector_dual_write:
        return None
    return "qdrant" if s.vector_backend == "pgvector" else "pgvector"


def _qdrant():
    # Imported lazily: on the default backend qdrant-client is never loaded.
    from app.stores import qdrant_store
    return qdrant_store


async def ensure_ready(session: AsyncSession | None = None) -> None:
    if backend() == "pgvector":
        await pgvector_store.ensure_ready(session)
    else:
        await _qdrant().ensure_collection()
    if _mirror() == "qdrant":
        try:
            await _qdrant().ensure_collection()
        except Exception:
            logger.warning("dual-write mirror (qdrant) not reachable at boot")


async def health() -> tuple[str, str]:
    """(dependency name, "ok" | "down: ...") for /readyz."""
    if backend() == "pgvector":
        return "pgvector", await pgvector_store.health()
    try:
        await _qdrant().get_qdrant().get_collections()
        return "qdrant", "ok"
    except Exception as exc:
        return "qdrant", f"down: {str(exc)[:80]}"


async def upsert_chunks(items: list[tuple[str, list[float], dict]],
                        session: AsyncSession | None = None) -> None:
    if backend() == "pgvector":
        await pgvector_store.upsert_chunks(items, session)
    else:
        await _qdrant().upsert_chunks(items)
    mirror = _mirror()
    if mirror:
        try:
            if mirror == "qdrant":
                await _qdrant().upsert_chunks(items)
            else:
                await pgvector_store.upsert_chunks(items, session)
        except Exception:
            _count_degraded("mirror_write")
            logger.warning("vector mirror write failed", extra={"mirror": mirror})


async def delete_document(document_id: str,
                          session: AsyncSession | None = None) -> None:
    if backend() == "pgvector":
        await pgvector_store.delete_document(document_id, session)
    else:
        await _qdrant().delete_document(document_id)
    mirror = _mirror()
    if mirror:
        try:
            if mirror == "qdrant":
                await _qdrant().delete_document(document_id)
            else:
                await pgvector_store.delete_document(document_id, session)
        except Exception:
            _count_degraded("mirror_delete")
            logger.warning("vector mirror delete failed", extra={"mirror": mirror})


async def search(vector: list[float], project_id: str, limit: int = 20,
                 document_ids: list[str] | None = None,
                 session: AsyncSession | None = None) -> list[tuple[str, float]]:
    if backend() == "pgvector":
        return await pgvector_store.search(vector, project_id, limit,
                                           document_ids, session)
    return await _qdrant().search(vector, project_id, limit, document_ids)


async def rank_within_document(project_id: str, document_id: str,
                               query_vectors: list[list[float]], limit: int = 20,
                               session: AsyncSession | None = None,
                               ) -> list[list[str]]:
    """Chunk ids of ONE document, nearest first, for each query vector.

    pgvector: one fetch of the document's vectors, ranked in memory.
    qdrant:   one filtered ANN call per query (the previous behaviour)."""
    if not query_vectors:
        return []
    if backend() == "pgvector":
        vecs = await pgvector_store.document_vectors(project_id, document_id, session)
        return [[cid for cid, _ in hits]
                for hits in pgvector_store.rank(query_vectors, vecs, limit)]
    out: list[list[str]] = []
    for qv in query_vectors:
        hits = await _qdrant().search(qv, project_id, limit, [document_id])
        out.append([cid for cid, _ in hits])
    return out


def _count_degraded(path: str) -> None:
    try:
        from app.core.observability import RETRIEVAL_DEGRADED
        RETRIEVAL_DEGRADED.labels(path).inc()
    except Exception:
        pass


def record_dense_failure(path: str) -> None:
    """Retrieval paths call this when dense ranking fails and they fall back to
    lexical-only. It used to be an `info` log line and nothing else - the
    report read exactly as confident with half its retrieval missing. Now it is
    a metric with an alert on it (deploy/observability/alerts.yml)."""
    _count_degraded(path)
