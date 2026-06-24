from app.ingestion.dedup import sha256_hex, titles_match


def test_sha256_stable():
    assert sha256_hex(b"abc") == sha256_hex(b"abc")
    assert sha256_hex(b"abc") != sha256_hex(b"abd")


def test_titles_exact():
    assert titles_match("Attention Is All You Need", "Attention is all you need")


def test_titles_punctuation_insensitive():
    assert titles_match(
        "BERT: Pre-training of Deep Bidirectional Transformers",
        "BERT - Pretraining of Deep Bidirectional Transformers",
    )


def test_titles_different_papers_not_matched():
    assert not titles_match(
        "Attention Is All You Need",
        "Sparse Attention Mechanisms for Long Documents",
    )


def test_empty_titles_never_match():
    assert not titles_match("", "")
    assert not titles_match("Some Title", "")
