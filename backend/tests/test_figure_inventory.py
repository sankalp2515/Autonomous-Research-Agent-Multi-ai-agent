"""Figures must be COUNTABLE, and must stay out of the text stream.

Measured over 8 papers / 162 pages of this corpus: **134 images produced 0
references in the extracted markdown.** `pymupdf4llm` drops images by default
(`write_images` and `embed_images` are both False), so a figure left no trace —
not a placeholder, not an anchor. Captions survive as ordinary body text, so a
report could cite "Figure 3 shows…" while the figure's contents were never read.

That is worse than a gap, it is an INVISIBLE gap: the four cell states can label
"the study does not report it" and "we could not establish it", but neither can
fire for evidence nobody knew existed. An inventory makes the absence sayable.

The second property is the one that protects everything else. The obvious way to
"turn on images" is `embed_images=True`, which injects base64 blobs into the
markdown — and that markdown becomes CHUNK TEXT: the exact bytes the quote gate
matches against and the embedder encodes. Figures are therefore inventoried
alongside the text, never inside it.
"""

import pytest

from app.ingestion.pdf_parser import (
    ParsedPage, _captions_on, _inventory_figures, _MIN_FIGURE_PX,
)


class _FakePage:
    def __init__(self, infos):
        self._infos = infos

    def get_image_info(self, xrefs=False):
        return self._infos


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __getitem__(self, i):
        return self._pages[i]


def _info(xref, w=400, h=300, bbox=(0, 0, 10, 10)):
    return {"xref": xref, "width": w, "height": h, "bbox": bbox}


def test_a_figure_is_recorded_with_its_address():
    doc = _FakeDoc([_FakePage([_info(11)])])
    pages = [ParsedPage(1, "Figure 1: Early, late and transmedia fusion.")]
    figs = _inventory_figures(doc, pages)
    assert len(figs) == 1
    f = figs[0]
    assert (f.page_number, f.xref) == (1, 11)
    assert f.caption.startswith("Figure 1:")


def test_page_furniture_is_not_counted_as_a_figure():
    """Rules, logos and bullet glyphs are bitmaps too. Counting them would
    manufacture a coverage problem that does not exist."""
    small = _MIN_FIGURE_PX - 1
    doc = _FakeDoc([_FakePage([_info(1, w=small, h=small), _info(2)])])
    figs = _inventory_figures(doc, [ParsedPage(1, "body text")])
    assert [f.xref for f in figs] == [2]


def test_the_same_image_tiled_twice_is_one_figure():
    doc = _FakeDoc([_FakePage([_info(7), _info(7)])])
    figs = _inventory_figures(doc, [ParsedPage(1, "")])
    assert len(figs) == 1


def test_a_broken_page_does_not_fail_the_document():
    """A figure inventory is an enrichment. A PDF whose image table is malformed
    must still ingest its text — the inventory degrades to 'we do not know what
    figures this paper has', which is an honest unknown, not a failure."""
    class _Boom:
        def get_image_info(self, xrefs=False):
            raise RuntimeError("malformed image table")

    doc = _FakeDoc([_Boom(), _FakePage([_info(3)])])
    figs = _inventory_figures(doc, [ParsedPage(1, ""), ParsedPage(2, "")])
    assert [f.xref for f in figs] == [3]


def test_a_paper_with_no_figures_reports_none():
    doc = _FakeDoc([_FakePage([])])
    assert _inventory_figures(doc, [ParsedPage(1, "text only")]) == []


@pytest.mark.parametrize("line,expected", [
    ("Figure 1: Early, late and transmedia fusion.", True),
    ("Fig. 1: The illustration of an QA-community system", True),
    ("Table 2: Results across benchmarks", True),
    ("The figure above is discussed in section 4", False),
])
def test_caption_detection(line, expected):
    assert bool(_captions_on(line)) is expected


def test_figures_never_enter_the_text_stream():
    """The load-bearing guarantee: chunk text is what the quote gate matches and
    what the embedder encodes. A figure must not add a single byte to it."""
    md = "Figure 1: A chart.\n\nThe method improves recall by 12 points."
    pages = [ParsedPage(1, md)]
    doc = _FakeDoc([_FakePage([_info(9)])])
    figs = _inventory_figures(doc, pages)
    assert figs and pages[0].markdown == md  # parser did not rewrite the page
