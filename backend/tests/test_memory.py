"""Memory ranking helpers — the recall logic, tested without a DB or ML."""

from app.services.memory import cosine, rank_by_embedding, rank_by_keyword


def test_cosine_basic():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert round(cosine([1.0, 1.0], [1.0, 0.0]), 3) == 0.707
    assert cosine([], [1.0]) == 0.0          # length mismatch / empty -> 0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector -> 0, no div error


def test_rank_by_embedding_orders_by_similarity_and_skips_missing():
    items = [
        ("a", [1.0, 0.0]),
        ("b", [0.0, 1.0]),
        ("c", None),          # no embedding -> excluded
        ("d", [0.9, 0.1]),
    ]
    ranked = rank_by_embedding([1.0, 0.0], items, k=3)
    texts = [t for t, _ in ranked]
    assert texts[0] == "a"           # exact match ranks first
    assert texts[1] == "d"           # near match second
    assert "c" not in texts          # embedding-less item skipped


def test_rank_by_keyword_prefers_term_overlap():
    texts = [
        "Researched retrieval augmented generation and hallucination.",
        "Researched unsupervised reinforcement learning for anomaly detection.",
        "Researched bias mitigation in decision systems.",
    ]
    ranked = rank_by_keyword("hallucination retrieval", texts, k=2)
    assert ranked[0] == texts[0]     # most term overlap first


def test_rank_by_keyword_falls_back_to_input_order_when_no_terms():
    texts = ["one", "two", "three"]
    # Query has only short (<=3 char) tokens -> no usable terms -> input order.
    assert rank_by_keyword("a to", texts, k=2) == ["one", "two"]
