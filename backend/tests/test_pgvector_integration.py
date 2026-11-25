"""pgvector SQL against a real Postgres. Skipped unless TEST_DATABASE_URL is set.

CI runs these after `alembic upgrade head` against pgvector/pgvector:pg16
(.github/workflows/ci.yml, "Integration tests"). Locally:

    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/research \\
        pytest -q -m integration
"""

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                       reason="needs TEST_DATABASE_URL (Postgres with pgvector)"),
]

DIM = 384


def _vec(*head: float) -> list[float]:
    v = [0.0] * DIM
    for i, x in enumerate(head):
        v[i] = x
    return v


@pytest.fixture
async def session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
        await s.rollback()  # every test leaves the database as it found it
    await engine.dispose()


async def _seed(session, project_id: str, n_docs: int = 2, per_doc: int = 3):
    from app.db.models import Chunk, Document, Project
    session.add(Project(id=project_id, owner_id="test", name="t"))
    await session.flush()
    chunks = []
    for d in range(n_docs):
        doc = Document(project_id=project_id, title=f"doc{d}", source_type="paper",
                       status="indexed")
        session.add(doc)
        await session.flush()
        for k in range(per_doc):
            c = Chunk(document_id=doc.id, project_id=project_id, text=f"t{d}{k}",
                      ordinal=k)
            session.add(c)
            chunks.append((doc.id, c))
    await session.flush()
    return chunks


async def test_schema_is_ready(session):
    from app.stores import pgvector_store
    await pgvector_store.ensure_ready(session)


async def test_upsert_then_exact_search_orders_by_cosine(session):
    from app.stores import pgvector_store
    pid = uuid.uuid4().hex
    chunks = await _seed(session, pid, n_docs=1, per_doc=3)
    a, b, c = (ch for _, ch in chunks)
    await pgvector_store.upsert_chunks([
        (a.id, _vec(1.0, 0.0), {}), (b.id, _vec(0.7, 0.7), {}), (c.id, _vec(0.0, 1.0), {}),
    ], session)
    hits = await pgvector_store.search(_vec(1.0, 0.0), pid, limit=3, session=session)
    assert [h[0] for h in hits] == [a.id, b.id, c.id]
    assert hits[0][1] == pytest.approx(1.0, abs=1e-5)


async def test_search_never_crosses_projects(session):
    """G3, closed corpus: the project predicate is the isolation boundary."""
    from app.stores import pgvector_store
    mine, theirs = uuid.uuid4().hex, uuid.uuid4().hex
    (_, m), = await _seed(session, mine, n_docs=1, per_doc=1)
    (_, t), = await _seed(session, theirs, n_docs=1, per_doc=1)
    await pgvector_store.upsert_chunks([(m.id, _vec(0.1, 1.0), {}),
                                        (t.id, _vec(1.0, 0.0), {})], session)
    hits = await pgvector_store.search(_vec(1.0, 0.0), mine, limit=10, session=session)
    assert [h[0] for h in hits] == [m.id]


async def test_document_scope_and_in_memory_rank_agree_with_sql(session):
    from app.stores import pgvector_store
    pid = uuid.uuid4().hex
    chunks = await _seed(session, pid, n_docs=2, per_doc=3)
    doc0 = chunks[0][0]
    await pgvector_store.upsert_chunks(
        [(c.id, _vec(1.0, float(i)), {}) for i, (_, c) in enumerate(chunks)], session)
    sql_hits = await pgvector_store.search(_vec(1.0, 0.0), pid, limit=3,
                                           document_ids=[doc0], session=session)
    vecs = await pgvector_store.document_vectors(pid, doc0, session)
    (mem_hits,) = pgvector_store.rank([_vec(1.0, 0.0)], vecs, limit=3)
    assert {h[0] for h in sql_hits} == {c.id for d, c in chunks if d == doc0}
    assert [h[0] for h in sql_hits] == [h[0] for h in mem_hits]


async def test_delete_document_clears_vectors_and_flag(session):
    from sqlalchemy import text

    from app.stores import pgvector_store
    pid = uuid.uuid4().hex
    chunks = await _seed(session, pid, n_docs=1, per_doc=2)
    doc = chunks[0][0]
    await pgvector_store.upsert_chunks([(c.id, _vec(1.0), {}) for _, c in chunks], session)
    await pgvector_store.delete_document(doc, session)
    left = await session.scalar(text(
        "SELECT count(*) FROM chunks WHERE document_id = :d "
        "AND (embedding IS NOT NULL OR embedded)"), {"d": doc})
    assert left == 0


async def test_a_failed_read_does_not_poison_the_callers_transaction(session):
    """Reads run in a SAVEPOINT. Without it, one failed vector query aborts
    the whole transaction and the run's next ordinary query fails too."""
    from sqlalchemy import text

    from app.stores import pgvector_store
    pid = uuid.uuid4().hex
    await _seed(session, pid, n_docs=1, per_doc=1)
    real = pgvector_store._QVEC
    try:
        pgvector_store._QVEC = "CAST(CAST(:q AS text) AS no_such_type)"
        with pytest.raises(Exception):
            await pgvector_store.search(_vec(1.0), pid, limit=1, session=session)
    finally:
        pgvector_store._QVEC = real
    assert await session.scalar(text("SELECT 1")) == 1
