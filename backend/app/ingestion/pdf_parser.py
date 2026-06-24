"""PDF parsing via PyMuPDF4LLM (tested choice, carried from v1).

v2 changes from v1: no 20-page cap - documents parse fully, with
per-page fallback so one broken page degrades one page, not the document.
Encrypted/corrupt files are classified, not crashed on.
"""

import asyncio
from dataclasses import dataclass

from app.core.exceptions import IngestError
from app.core.logging import get_logger

logger = get_logger("ingest.pdf")


@dataclass
class ParsedPage:
    page_number: int  # 1-based
    markdown: str


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    page_count: int
    failed_pages: list[int]

    @property
    def full_markdown(self) -> str:
        return "\n\n".join(p.markdown for p in self.pages)


def _parse_sync(pdf_bytes: bytes) -> ParsedDocument:
    import pymupdf  # PyMuPDF
    import pymupdf4llm

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise IngestError("unreadable PDF", detail={"error": str(exc)[:200]}) from exc

    if doc.needs_pass:
        doc.close()
        raise IngestError("encrypted PDF - password required")
    if doc.page_count == 0:
        doc.close()
        raise IngestError("PDF has no pages")

    pages: list[ParsedPage] = []
    failed: list[int] = []
    try:
        # page_chunks=True returns one dict per page with 'text' (markdown),
        # preserving page provenance for span-level citations.
        chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)
        for idx, chunk in enumerate(chunks):
            md = (chunk.get("text") or "").strip()
            pages.append(ParsedPage(page_number=idx + 1, markdown=md))
    except Exception:
        # Whole-document pass failed: degrade to per-page parsing so a
        # single malformed page costs one page, not the document.
        logger.warning("document-level parse failed; falling back to per-page")
        pages = []
        for idx in range(doc.page_count):
            try:
                md = pymupdf4llm.to_markdown(doc, pages=[idx])
                pages.append(ParsedPage(page_number=idx + 1, markdown=md.strip()))
            except Exception:
                failed.append(idx + 1)
                pages.append(ParsedPage(page_number=idx + 1, markdown=""))

    page_count = doc.page_count
    doc.close()

    if all(not p.markdown for p in pages):
        raise IngestError(
            "no extractable text (likely a scanned PDF - OCR not yet enabled)",
            detail={"pages": page_count},
        )
    if failed:
        logger.warning("some pages failed to parse", extra={"failed_pages": failed})
    return ParsedDocument(pages=pages, page_count=page_count, failed_pages=failed)


async def parse_pdf(pdf_bytes: bytes, *, max_mb: int = 50) -> ParsedDocument:
    if len(pdf_bytes) > max_mb * 1024 * 1024:
        raise IngestError(f"PDF exceeds {max_mb}MB limit",
                          detail={"size_mb": round(len(pdf_bytes) / 1048576, 1)})
    return await asyncio.to_thread(_parse_sync, pdf_bytes)
