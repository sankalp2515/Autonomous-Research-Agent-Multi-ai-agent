from app.retrieval.hybrid import rrf_fuse


def test_rrf_rewards_agreement():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"]])
    assert fused["a"] > fused["c"]
    assert fused["b"] > fused["c"]
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_single_ranking():
    fused = rrf_fuse([["x", "y"]])
    assert fused["x"] > fused["y"]


def test_rrf_empty():
    assert rrf_fuse([]) == {}
    assert rrf_fuse([[]]) == {}
