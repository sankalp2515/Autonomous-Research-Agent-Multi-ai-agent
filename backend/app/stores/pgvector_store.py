"""pgvector: dense vectors on the chunk row, in the system of record.

Why vectors moved here from Qdrant (docs/PRODUCTION_READINESS.md has the full
case):

* One store cannot drift. Chunk text and chunk vector used to be written to two
  systems with no shared transaction, and a delete had to reach both. Now the
  vector is a column on the row it describes; a rolled-back ingest rolls back
  its vectors with it.
* One store cannot fail on its own. When Qdrant was down, both retrieval paths
  quietly degraded to lexical-only and the report read exactly as confident.
  A Postgres outage stops the run instead, which is the honest outcome.
* Tenancy is enforced in one place. The project filter is the same SQL
  predicate every other query uses, not a payload filter in a second system.
* At our scale exact search is both faster and better. A project holds a few
  thousand chunks; a sequential scan over them with `<=>` takes milliseconds and
  never misses a neighbour, where an ANN index trades recall for speed we do
  not need. Add HNSW only past ~100k chunks per project (see SCALING.md).

DRIVER NOTE: values cross the wire as TEXT and are cast in SQL
(`CAST(CAST(:v AS text) AS vector)`), and only `embedding::text` is ever
selected. asyncpg has no codec for `vector`; casting keeps the driver out of it
so there is no per-connection codec registration to forget.

SESSION NOTE: every read runs inside a SAVEPOINT. Retrieval treats a dense
failure as degradable, and a failed statement on a shared session would
otherwise abort the caller's whole transaction ("current transaction is
aborted"), turning a degraded ranking into a failed run.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import numpy as np
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import EMBEDDING_DIM

logger = get_logger("pgvector")


class VectorStoreNotReady(RuntimeError):
    """The database cannot hold vectors as this build expects. Raised at boot."""


# ── encoding ────────────────────────────────────────────────────────────────

def to_literal(vec: Sequence[float], dim: int | None = None) -> str:
    """`[0.1,0.2,...]` - pgvector's text input format.

    Validates width and finiteness HERE, because Postgres would reject a NaN or
    a wrong-width vector only at statement time, inside an ingest that has
    already spent the embedding call."""
    dim = dim or get_settings().embedding_dim
    if len(vec) != dim:
        raise ValueError(f"vector has {len(vec)} dims, column expects {dim}")
    parts = []
    for x in vec:
        f = float(x)
        if not math.isfinite(f):
            raise ValueError("vector contains a non-finite value")
        parts.append(format(f, ".7g"))
    return "[" + ",".join(parts) + "]"


def from_literal(raw: str) -> np.ndarray:
    body = raw.strip()
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    if not body:
        return np.zeros(0, dtype=np.float32)
    return np.array(body.split(","), dtype=np.float32)


_QVEC = "CAST(CAST(:q AS text) AS vector)"


@asynccontextmanager
async def _scope(session: AsyncSession | None) -> AsyncIterator[AsyncSession]:
    """Use the caller's session (so uncommitted chunk rows are visible), or open
    one. Reads inside the caller's session are wrapped in a SAVEPOINT."""
    if session is not None:
        yield session
        return
    from app.db.session import session_scope
    async with session_scope() as s:
        yield s


def _is_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


# ── lifecycle ───────────────────────────────────────────────────────────────

async def ensure_ready(session: AsyncSession | None = None) -> None:
    """Refuse to boot unless the column exists with the width this build writes.

    Three mismatches are caught here instead of on the first ingest: the
    extension is missing, the migration that adds `chunks.embedding` has not run,
    or EMBEDDING_MODEL was changed to a model of a different width without a
    migration (which would otherwise fail every insert, or - worse, if widths
    happened to match - mix two models' vectors in one index)."""
    settings = get_settings()
    if settings.embedding_dim != EMBEDDING_DIM:
        raise VectorStoreNotReady(
            f"EMBEDDING_DIM={settings.embedding_dim} but the schema column is "
            f"vector({EMBEDDING_DIM}); changing the embedding width needs a migration")
    async with _scope(session) as s:
        if not _is_postgres(s):
            return
        ext = await s.scalar(text(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        if ext is None:
            raise VectorStoreNotReady(
                "pgvector extension is not installed; run `alembic upgrade head` "
                "(Cloud SQL / Supabase ship it; the local image is pgvector/pgvector:pg16)")
        typmod = await s.scalar(text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding' "
            "AND NOT attisdropped"))
        if typmod is None:
            raise VectorStoreNotReady(
                "chunks.embedding is missing; run `alembic upgrade head`")
        if int(typmod) != EMBEDDING_DIM:
            raise VectorStoreNotReady(
                f"chunks.embedding is vector({typmod}), this build writes "
                f"vector({EMBEDDING_DIM})")
    logger.info("pgvector ready", extra={"extension": ext, "dim": EMBEDDING_DIM})


async def health(session: AsyncSession | None = None) -> str:
    try:
        await ensure_ready(session)
        return "ok"
    except Exception as exc:  # pragma: no cover - reported, never raised
        return f"down: {str(exc)[:80]}"


# ── writes ──────────────────────────────────────────────────────────────────

async def upsert_chunks(items: list[tuple[str, list[float], dict]],
                        session: AsyncSession | None = None) -> None:
    """items: (chunk_id, vector, payload). Payload is accepted for interface
    parity with the Qdrant store and ignored: project and document are already
    columns on the row."""
    if not items:
        return
    params = [{"id": cid, "v": to_literal(vec)} for cid, vec, _ in items]
    async with _scope(session) as s:
        if not _is_postgres(s):
            return
        # The rows may have been added in this session and not flushed yet; an
        # UPDATE issued before the INSERT reaches the server matches nothing.
        await s.flush()
        await s.execute(text(
            "UPDATE chunks SET embedding = CAST(CAST(:v AS text) AS vector), "
            "embedded = true WHERE id = :id"), params)


async def delete_document(document_id: str,
                          session: AsyncSession | None = None) -> None:
    async with _scope(session) as s:
        if not _is_postgres(s):
            return
        await s.execute(text(
            "UPDATE chunks SET embedding = NULL, embedded = false "
            "WHERE document_id = :d"), {"d": document_id})


# ── reads ───────────────────────────────────────────────────────────────────

async def search(vector: list[float], project_id: str, limit: int = 20,
                 document_ids: list[str] | None = None,
                 session: AsyncSession | None = None) -> list[tuple[str, float]]:
    """(chunk_id, cosine similarity), nearest first, restricted to one project.

    Exact: an ordered scan with `<=>` (cosine distance), no ANN index. The
    closed-corpus guarantee (G3) is the `project_id` predicate."""
    q = to_literal(vector)
    sql = (f"SELECT id, 1 - (embedding <=> {_QVEC}) AS score FROM chunks "
           "WHERE project_id = :pid AND embedding IS NOT NULL")
    params: dict = {"q": q, "pid": project_id, "lim": int(limit)}
    if document_ids:
        sql += " AND document_id IN :docs"
        params["docs"] = list(document_ids)
    sql += f" ORDER BY embedding <=> {_QVEC} LIMIT :lim"
    stmt = text(sql)
    if document_ids:
        stmt = stmt.bindparams(bindparam("docs", expanding=True))
    async with _scope(session) as s:
        if not _is_postgres(s):
            return []
        async with s.begin_nested():
            rows = (await s.execute(stmt, params)).all()
    return [(r[0], float(r[1])) for r in rows]


async def document_vectors(project_id: str, document_id: str,
                           session: AsyncSession | None = None) -> dict[str, np.ndarray]:
    """Every vector of one document, in one round trip.

    Per-paper extraction ranks a ~60-chunk document against 15-25 dimension
    queries. Against Qdrant that was one network call per query; here it is one
    fetch per paper and the ranking is an in-memory matrix product."""
    async with _scope(session) as s:
        if not _is_postgres(s):
            return {}
        async with s.begin_nested():
            rows = (await s.execute(text(
                "SELECT id, CAST(embedding AS text) FROM chunks "
                "WHERE project_id = :p AND document_id = :d "
                "AND embedding IS NOT NULL"), {"p": project_id, "d": document_id})).all()
    return {cid: from_literal(raw) for cid, raw in rows}


def rank(query_vectors: list[list[float]], doc_vectors: dict[str, np.ndarray],
         limit: int = 20) -> list[list[tuple[str, float]]]:
    """Exact cosine ranking of each query against a small candidate set.

    Ties break on chunk id so the ordering - and therefore the extraction
    window - is deterministic run to run."""
    if not doc_vectors or not query_vectors:
        return [[] for _ in query_vectors]
    ids = sorted(doc_vectors)
    m = np.stack([doc_vectors[i] for i in ids]).astype(np.float32)
    m_norm = np.linalg.norm(m, axis=1)
    m_norm[m_norm == 0] = 1.0
    m = m / m_norm[:, None]
    out: list[list[tuple[str, float]]] = []
    for qv in query_vectors:
        q = np.asarray(qv, dtype=np.float32)
        n = float(np.linalg.norm(q)) or 1.0
        sims = m @ (q / n)
        order = sorted(range(len(ids)), key=lambda k: (-float(sims[k]), ids[k]))[:limit]
        out.append([(ids[k], float(sims[k])) for k in order])
    return out
