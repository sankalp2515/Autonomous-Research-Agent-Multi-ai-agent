"""Dense vectors on the chunk row (pgvector) - the parts that need no database.

The SQL itself runs in tests/test_pgvector_integration.py against a real
Postgres with pgvector (CI). These pin the encoding, the in-memory ranking
the per-paper extraction relies on, and that the facade routes to the backend
the config names.
"""

import math

import numpy as np
import pytest

from app.stores import pgvector_store as pg
from app.stores import vector_store


def test_literal_round_trips():
    vec = [0.1, -0.25, 3.0, 1e-8]
    lit = pg.to_literal(vec, dim=4)
    assert lit.startswith("[") and lit.endswith("]")
    back = pg.from_literal(lit)
    assert np.allclose(back, vec, rtol=1e-6, atol=1e-12)


def test_wrong_width_is_refused_before_the_database_sees_it():
    with pytest.raises(ValueError, match="dims"):
        pg.to_literal([0.1, 0.2], dim=384)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_refused(bad):
    with pytest.raises(ValueError, match="non-finite"):
        pg.to_literal([0.0, bad, 1.0], dim=3)


def test_rank_orders_by_cosine_not_by_magnitude():
    docs = {
        "same_direction_small": np.array([1.0, 0.0], dtype=np.float32),
        "orthogonal_large": np.array([0.0, 100.0], dtype=np.float32),
        "close_large": np.array([10.0, 1.0], dtype=np.float32),
    }
    (hits,) = pg.rank([[2.0, 0.0]], docs, limit=3)
    assert [cid for cid, _ in hits] == [
        "same_direction_small", "close_large", "orthogonal_large"]
    assert hits[0][1] == pytest.approx(1.0)


def test_rank_ties_break_on_chunk_id_so_the_window_is_deterministic():
    v = np.array([1.0, 1.0], dtype=np.float32)
    docs = {"c3": v, "c1": v, "c2": v}
    (a,) = pg.rank([[1.0, 1.0]], docs, limit=3)
    (b,) = pg.rank([[1.0, 1.0]], dict(reversed(list(docs.items()))), limit=3)
    assert [c for c, _ in a] == [c for c, _ in b] == ["c1", "c2", "c3"]


def test_rank_respects_limit_and_handles_empty_inputs():
    docs = {f"c{i}": np.array([1.0, float(i)], dtype=np.float32) for i in range(10)}
    (hits,) = pg.rank([[1.0, 0.0]], docs, limit=4)
    assert len(hits) == 4
    assert pg.rank([[1.0, 0.0]], {}, limit=4) == [[]]
    assert pg.rank([], docs, limit=4) == []


def test_zero_vectors_do_not_divide_by_zero():
    docs = {"z": np.zeros(2, dtype=np.float32), "a": np.array([1.0, 0.0], dtype=np.float32)}
    (hits,) = pg.rank([[0.0, 0.0]], docs, limit=2)
    assert all(math.isfinite(s) for _, s in hits)


class _S:
    def __init__(self, backend, dual=False):
        self.vector_backend = backend
        self.vector_dual_write = dual


async def test_facade_reads_pgvector_by_default(monkeypatch):
    calls = []

    async def fake_search(vec, pid, limit, docs, session):
        calls.append(("pg", pid, limit, docs))
        return [("c1", 0.9)]

    monkeypatch.setattr(vector_store, "get_settings", lambda: _S("pgvector"))
    monkeypatch.setattr(pg, "search", fake_search)
    out = await vector_store.search([0.1], "p1", limit=5, document_ids=["d1"])
    assert out == [("c1", 0.9)]
    assert calls == [("pg", "p1", 5, ["d1"])]


async def test_rank_within_document_is_one_fetch_not_one_call_per_query(monkeypatch):
    """The latency fix: a paper's 15-25 dimension queries used to be 15-25
    network round trips. On pgvector they are one fetch."""
    fetches = []

    async def fake_vectors(pid, doc, session):
        fetches.append(doc)
        return {"c1": np.array([1.0, 0.0], dtype=np.float32),
                "c2": np.array([0.0, 1.0], dtype=np.float32)}

    monkeypatch.setattr(vector_store, "get_settings", lambda: _S("pgvector"))
    monkeypatch.setattr(pg, "document_vectors", fake_vectors)
    ranked = await vector_store.rank_within_document(
        "p", "doc", [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], limit=2)
    assert fetches == ["doc"]
    assert ranked[0][0] == "c1" and ranked[1][0] == "c2"


async def test_mirror_write_failure_never_fails_the_primary(monkeypatch):
    primary = []

    async def ok_upsert(items, session):
        primary.append(len(items))

    class _BrokenQdrant:
        @staticmethod
        async def upsert_chunks(items):
            raise ConnectionError("qdrant down")

    monkeypatch.setattr(vector_store, "get_settings", lambda: _S("pgvector", dual=True))
    monkeypatch.setattr(pg, "upsert_chunks", ok_upsert)
    monkeypatch.setattr(vector_store, "_qdrant", lambda: _BrokenQdrant)
    await vector_store.upsert_chunks([("c1", [0.1], {})])
    assert primary == [1]


async def test_dimension_retrieval_uses_one_vector_fetch_per_paper(monkeypatch):
    """End to end through retrieve_by_dimension: however many axes and query
    angles there are, the paper's vectors are fetched once."""
    import app.retrieval.dimension as dim_mod
    from tests.test_dimension_retrieval import ACCURACY, LATENCY, TOKENS, _paper

    chunks = _paper()
    rank_calls = []

    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]

    async def fake_load(_session, _project, _doc):
        return chunks, "A Paper", False

    async def fake_rank(project_id, doc_id, vectors, limit=20, session=None):
        rank_calls.append((doc_id, len(vectors)))
        return [[c.id for c in chunks][:limit] for _ in vectors]

    monkeypatch.setattr(dim_mod, "embed_texts", fake_embed)
    monkeypatch.setattr(dim_mod, "_load_document_chunks", fake_load)
    monkeypatch.setattr(dim_mod.vector_store, "rank_within_document", fake_rank)

    await dim_mod.retrieve_by_dimension(
        None, "p", "doc1", [ACCURACY, LATENCY, TOKENS],
        entities=["graphrag"], objective="compare GraphRAG vs standard RAG",
        per_dimension_k=4, max_chunks=12, use_rerank=False,
    )
    assert len(rank_calls) == 1
    assert rank_calls[0][0] == "doc1" and rank_calls[0][1] > 3


async def test_dense_failure_is_counted_not_silent(monkeypatch):
    import app.retrieval.dimension as dim_mod
    from app.core.observability import RETRIEVAL_DEGRADED
    from tests.test_dimension_retrieval import ACCURACY, _paper

    chunks = _paper()

    async def fake_embed(texts):
        return [[1.0, 0.0] for _ in texts]

    async def fake_load(_session, _project, _doc):
        return chunks, "A Paper", False

    async def broken_rank(*a, **k):
        raise ConnectionError("database gone")

    monkeypatch.setattr(dim_mod, "embed_texts", fake_embed)
    monkeypatch.setattr(dim_mod, "_load_document_chunks", fake_load)
    monkeypatch.setattr(dim_mod.vector_store, "rank_within_document", broken_rank)
    before = RETRIEVAL_DEGRADED.labels("dimension")._value.get()
    out, _ = await dim_mod.retrieve_by_dimension(
        None, "p", "doc1", [ACCURACY], entities=[], objective="x",
        per_dimension_k=4, max_chunks=8, use_rerank=False)
    assert out, "lexical ranking must still return evidence"
    assert RETRIEVAL_DEGRADED.labels("dimension")._value.get() == before + 1
