from app.ingestion.chunker import MIN_CHARS, TARGET_CHARS, chunk_pages


def _page(n: int, paragraphs: list[str]) -> tuple[int, str]:
    return (n, "\n\n".join(paragraphs))


def test_empty_input():
    chunks, full = chunk_pages([])
    assert chunks == [] and full == ""


def test_blank_pages_skipped():
    chunks, _ = chunk_pages([(1, "   \n\n  "), (2, "Real content paragraph " * 20)])
    assert len(chunks) >= 1
    assert all(c.text.strip() for c in chunks)


def test_section_headings_tracked():
    pages = [_page(1, ["# Introduction", "intro text " * 60,
                       "## Methods", "methods text " * 60])]
    chunks, _ = chunk_pages(pages)
    sections = {c.section for c in chunks}
    assert "Introduction" in sections
    assert "Methods" in sections


def test_chunks_respect_target_size():
    pages = [_page(1, ["word " * 100 for _ in range(30)])]
    chunks, _ = chunk_pages(pages)
    assert len(chunks) > 1
    # generous bound: target + one paragraph
    assert all(len(c.text) < TARGET_CHARS + 600 for c in chunks)


def test_tiny_tail_merged_not_emitted():
    pages = [_page(1, ["long paragraph " * 80, "tiny."])]
    chunks, _ = chunk_pages(pages)
    assert all(len(c.text) >= MIN_CHARS for c in chunks)


def test_page_provenance():
    pages = [_page(1, ["alpha " * 150]), _page(2, ["beta " * 150])]
    chunks, _ = chunk_pages(pages)
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2


def test_char_offsets_locate_text():
    pages = [_page(1, ["first paragraph of the document " * 10,
                       "second paragraph with marker XYZZY " * 10])]
    chunks, full_md = chunk_pages(pages)
    for c in chunks:
        assert full_md[c.char_start:c.char_end].strip().startswith(
            c.text.split("\n\n")[0][:30]
        )


def test_ordinals_sequential():
    pages = [_page(1, ["para " * 120 for _ in range(10)])]
    chunks, _ = chunk_pages(pages)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
