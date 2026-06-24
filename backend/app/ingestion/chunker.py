"""Section-aware chunker (carried from v1, hardened).

Input: per-page markdown from pymupdf4llm. Output: chunks that carry
section heading, page range, and char offsets into the document's full
markdown - the provenance spine for span-level citations.

Pure python; unit-tested.
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,4})\s+(.+)$")
_MD_MARKS = re.compile(r"[*_`#]+")


def _clean_heading(text: str) -> str:
    """Strip markdown emphasis/heading markers pymupdf4llm leaves in headings
    (e.g. '**1 Introduction**' -> '1 Introduction') so section labels render
    clean in the UI and read naturally as retrieval context."""
    return _MD_MARKS.sub("", text).strip()

TARGET_CHARS = 1400
MIN_CHARS = 200
OVERLAP_CHARS = 150


@dataclass
class RawChunk:
    section: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    ordinal: int
    text: str


@dataclass
class _Block:
    text: str
    page: int
    char_start: int


def _split_blocks(pages: list[tuple[int, str]]) -> tuple[list[_Block], str]:
    """Flatten pages to paragraph blocks with global char offsets."""
    blocks: list[_Block] = []
    full_parts: list[str] = []
    offset = 0
    for page_number, md in pages:
        for para in re.split(r"\n{2,}", md):
            para = para.strip("\n")
            if not para.strip():
                continue
            blocks.append(_Block(text=para, page=page_number, char_start=offset))
            full_parts.append(para)
            offset += len(para) + 2  # the join separator
    return blocks, "\n\n".join(full_parts)


def chunk_pages(pages: list[tuple[int, str]]) -> tuple[list[RawChunk], str]:
    """pages: (page_number, markdown). Returns (chunks, full_markdown)."""
    blocks, full_md = _split_blocks(pages)
    chunks: list[RawChunk] = []
    section = ""
    buf: list[_Block] = []
    buf_len = 0
    ordinal = 0

    def flush():
        nonlocal buf, buf_len, ordinal
        if not buf:
            return
        text = "\n\n".join(b.text for b in buf)
        if len(text.strip()) < MIN_CHARS and chunks:
            # Tiny tail: merge into the previous chunk instead of emitting
            # an unretrievable fragment.
            prev = chunks[-1]
            prev.text = prev.text + "\n\n" + text
            prev.char_end = buf[-1].char_start + len(buf[-1].text)
            prev.page_end = max(prev.page_end, buf[-1].page)
        else:
            chunks.append(RawChunk(
                section=section,
                page_start=buf[0].page,
                page_end=buf[-1].page,
                char_start=buf[0].char_start,
                char_end=buf[-1].char_start + len(buf[-1].text),
                ordinal=ordinal,
                text=text,
            ))
            ordinal += 1
        buf, buf_len = [], 0

    for block in blocks:
        first_line = block.text.split("\n", 1)[0]
        heading = _HEADING.match(first_line)
        if heading:
            flush()
            section = _clean_heading(heading.group(2))
        block_len = len(block.text)
        if buf_len + block_len > TARGET_CHARS and buf:
            flush()
        buf.append(block)
        buf_len += block_len + 2
    flush()
    return chunks, full_md
