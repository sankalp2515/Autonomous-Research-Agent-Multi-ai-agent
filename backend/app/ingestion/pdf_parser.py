"""PDF parsing via PyMuPDF4LLM (tested choice, carried from v1).

v2 changes from v1: no 20-page cap - documents parse fully, with
per-page fallback so one broken page degrades one page, not the document.
Encrypted/corrupt files are classified, not crashed on.
"""

import asyncio
import re
from dataclasses import dataclass, field

from app.core.exceptions import IngestError
from app.core.logging import get_logger

logger = get_logger("ingest.pdf")


@dataclass
class ParsedPage:
    page_number: int  # 1-based
    markdown: str


@dataclass
class ParsedFigure:
    """One figure located on a page — an ADDRESS, never pixels.

    We record where a figure is and what its caption says; we do not copy the
    bitmap. The PDF is already retained in the device library, so a later reader
    (a vision model, an export, a viewer) can re-extract the exact region on
    demand from `page` + `bbox`. Storing the bytes again would duplicate the
    heaviest part of the corpus for data we can always recompute.
    """
    page_number: int          # 1-based
    xref: int                 # PDF object id — re-extract with doc.extract_image
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    caption: str = ""         # nearest "Figure N: …" line on the page, if any


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    page_count: int
    failed_pages: list[int]
    # WHY FIGURES ARE INVENTORIED SEPARATELY FROM THE TEXT.
    #
    # pymupdf4llm drops images entirely by default (write_images and
    # embed_images are both False), so a figure left NO trace: not a
    # placeholder, not an anchor, nothing. Measured over 8 papers / 162 pages of
    # this corpus, 134 images produced 0 references in the markdown. Captions
    # survive as body text, so a report could cite "Figure 3 shows…" while the
    # figure's actual content was never read — and the cell-state machinery
    # could not even mark that as `extraction_uncertain`, because nothing knew a
    # figure had been there.
    #
    # The fix is an inventory, NOT an injection. Turning `embed_images` on would
    # push base64 blobs into the markdown, and that markdown becomes chunk text
    # — the exact bytes the quote gate matches against and the embedder reads.
    # Keeping figures out of the text stream means the grounding contract is
    # untouched while absence becomes countable.
    figures: list[ParsedFigure] = field(default_factory=list)

    @property
    def full_markdown(self) -> str:
        return "\n\n".join(p.markdown for p in self.pages)


# A figure's caption is the one piece of a figure that ALREADY survives
# extraction — it is body text. Pairing it with the image address is what makes
# an un-read figure nameable ("Figure 4, p.7, not read") rather than invisible.
_CAPTION = re.compile(r"^\s*(?:!\[[^\]]*\]\([^)]*\)\s*)?"
                      r"((?:figure|fig\.?|table|chart)\s*\d+[.:)]?\s+.{0,240})",
                      re.I | re.M)
# Below this, a bitmap is furniture — a rule, a logo, a bullet glyph. Counting
# those as "figures we failed to read" would manufacture a coverage problem that
# does not exist.
_MIN_FIGURE_PX = 100


def _captions_on(markdown: str) -> list[str]:
    return [re.sub(r"\s+", " ", m.group(1)).strip() for m in _CAPTION.finditer(markdown)]


def _inventory_figures(doc, pages: list[ParsedPage]) -> list[ParsedFigure]:
    """Locate every substantive figure and pair it with the nearest caption.

    Deliberately best-effort and non-fatal: a figure inventory is an enrichment,
    and a PDF whose image table is malformed must still ingest its text. A
    missing inventory degrades to "we do not know what figures this paper has",
    which is the same honest unknown the cell states already model.
    """
    figures: list[ParsedFigure] = []
    for idx in range(doc.page_count):
        try:
            page = doc[idx]
            captions = _captions_on(pages[idx].markdown if idx < len(pages) else "")
            seen: set[int] = set()
            for info in page.get_image_info(xrefs=True):
                xref = info.get("xref", 0)
                w, h = int(info.get("width", 0)), int(info.get("height", 0))
                if w < _MIN_FIGURE_PX or h < _MIN_FIGURE_PX:
                    continue
                if xref and xref in seen:   # the same image tiled/repeated
                    continue
                seen.add(xref)
                figures.append(ParsedFigure(
                    page_number=idx + 1, xref=xref,
                    bbox=tuple(round(v, 2) for v in info.get("bbox", (0, 0, 0, 0))),
                    width=w, height=h,
                    # Positional pairing: the Nth substantive image on a page
                    # takes the Nth caption on that page. Crude, and right far
                    # more often than not for single-column papers — but it is a
                    # LABEL, never evidence, so a wrong pairing costs a confusing
                    # figure name and can never reach a verified claim.
                    caption=captions[len(seen) - 1] if len(seen) <= len(captions) else "",
                ))
        except Exception:
            logger.debug("figure inventory failed for a page", extra={"page": idx + 1})
    return figures


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
    figures = _inventory_figures(doc, pages)
    doc.close()

    if all(not p.markdown for p in pages):
        raise IngestError(
            "no extractable text (likely a scanned PDF - OCR not yet enabled)",
            detail={"pages": page_count},
        )
    if failed:
        logger.warning("some pages failed to parse", extra={"failed_pages": failed})
    return ParsedDocument(pages=pages, page_count=page_count, failed_pages=failed,
                          figures=figures)


async def parse_pdf(pdf_bytes: bytes, *, max_mb: int = 50) -> ParsedDocument:
    if len(pdf_bytes) > max_mb * 1024 * 1024:
        raise IngestError(f"PDF exceeds {max_mb}MB limit",
                          detail={"size_mb": round(len(pdf_bytes) / 1048576, 1)})
    return await asyncio.to_thread(_parse_sync, pdf_bytes)
