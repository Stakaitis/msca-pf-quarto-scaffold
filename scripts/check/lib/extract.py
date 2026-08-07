"""Pull positioned text and geometry out of a PDF.

The checks compare numbers; this module is where those numbers come from."""

from __future__ import annotations

import re
from typing import Iterator, Sequence

from ._pymupdf import fitz
from .model import Span
from .rules import (CAPTION_RE, FOOTER_RE, MATH_COMPANION_RE, REF_MARKER_RE,
                    TIMES_RE)

def iter_spans(doc: "fitz.Document") -> Iterator[Span]:
    """Yield every positioned text run in the document.

    Args:
        doc: An open PyMuPDF document.

    Yields:
        One :class:`Span` per styled run, in page then reading order.
    """
    for page_index, page in enumerate(doc):
        # Rectangles of every placed image, so text drawn over one can be
        # recognised as figure content rather than body prose.
        for block in page.get_text("dict")["blocks"]:
            lines = block.get("lines", [])
            block_text = "".join(
                span["text"] for line in lines for span in line["spans"]
            )
            for line in lines:
                for span in line["spans"]:
                    yield Span(
                        page=page_index + 1,
                        text=span["text"],
                        font=strip_subset_prefix(span["font"]),
                        size=round(span["size"], 2),
                        bbox=tuple(span["bbox"]),  # type: ignore[arg-type]
                        block_text=block_text,
                    )


def strip_subset_prefix(font_name: str) -> str:
    """Remove the six-letter subset tag PDF writers prepend to font names.

    ``ZFRQFY+TeXGyreTermes-Bold`` becomes ``TeXGyreTermes-Bold``.

    Args:
        font_name: Font name exactly as recorded in the PDF.

    Returns:
        The font name without its subset prefix.
    """
    return font_name.split("+", 1)[-1]


def is_footer(span: Span) -> bool:
    """Report whether a span is part of the mandated page footer.

    Args:
        span: The span to classify.

    Returns:
        True if the span's text matches the ``Part B - Page X of Y`` footer.
    """
    return bool(FOOTER_RE.search(span.text) or FOOTER_RE.search(span.block_text))


def is_exempt_from_body_size(span: Span) -> tuple[bool, str]:
    """Decide whether a span may legitimately be smaller than 11 pt.

    The form allows "text elements other than the body text, such as headers,
    foot/end notes, captions, formulas, etc." down to 8 pt. Three concrete
    kinds occur in this document.

    Args:
        span: The span to classify.

    Returns:
        A ``(exempt, zone)`` pair; ``zone`` names the exemption or is empty.
    """
    if is_footer(span):
        return True, "footer"
    if CAPTION_RE.match(span.block_text):
        return True, "caption"
    if REF_MARKER_RE.match(span.text.strip()) and span.text.strip():
        return True, "reference marker"
    if not (TIMES_RE.search(span.font) or MATH_COMPANION_RE.search(span.font)):
        # Not set in the body face, so by the rules' own definition it is not
        # body text: "the reference font for the BODY TEXT ... is Times New
        # Roman". Figure labels and chart axes arrive in the chart tool's font
        # and are allowed down to the 8 pt floor, which is still enforced below.
        #
        # This cannot be used to smuggle in an under-size body: if a non-Times
        # face covers a meaningful share of the document, check_fonts fails it
        # outright. Geometry was tried first and rejected -- a vector figure is
        # a Form XObject whose reported bbox is in its own coordinate space, not
        # the page's, so intersection tests silently measured the wrong region.
        return True, "non-body face (figure/caption)"
    return False, ""


def body_bbox(page: "fitz.Page") -> "fitz.Rect | None":
    """Compute the bounding box of body text on a page, excluding the footer.

    The margin rule reads "not including any footers or headers", so the
    footer -- which sits by design in the bottom margin -- must be dropped
    before measuring, or every compliant page measures a ~6 mm bottom margin.

    Args:
        page: The page to measure.

    Images and vector graphics are measured too. They used to be invisible
    here, because only text blocks carry a "lines" key -- which meant a Quarto
    figure wider than the text column (`![](g.png){width=190mm}` against a
    178 mm column) sat 4 mm from the paper edge while this function still
    reported a 16 mm margin. A Gantt chart is expected in Section 3, so that
    blind spot was one figure away from going live.

    Args:
        page: The page to measure.

    Returns:
        The union of all non-footer body geometry, or None if the page carries
        nothing measurable at all.
    """
    box: "fitz.Rect | None" = None

    def add(rect: "fitz.Rect") -> None:
        nonlocal box
        if rect.is_empty or rect.is_infinite:
            return
        box = rect if box is None else (box | rect)

    for block in page.get_text("dict")["blocks"]:
        lines = block.get("lines", [])
        text = "".join(s["text"] for line in lines for s in line["spans"])
        if FOOTER_RE.search(text):
            continue
        for line in lines:
            add(fitz.Rect(line["bbox"]))

    # Raster images: block type 1 in the dict, but get_image_rects is the
    # reliable accessor for their placed rectangle.
    for img in page.get_images(full=True):
        for rect in page.get_image_rects(img[0]):
            add(fitz.Rect(rect))

    # Vector ink: table rules, boxes, drawn Gantt bars. A full-page background
    # fill would swamp the measurement, so ignore anything that covers
    # essentially the whole page.
    page_area = abs(page.rect)
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        if abs(rect) > 0.95 * page_area:
            continue
        add(rect)

    return box


def _font_char_share(spans: Sequence[Span], names: Sequence[str]) -> float:
    """Fraction of all characters set in any of the named fonts.

    Args:
        spans: Every text run in the document.
        names: Font names to measure.

    Returns:
        Share between 0.0 and 1.0; 0.0 when the document has no text.
    """
    wanted = set(names)
    total = sum(len(s.text) for s in spans)
    if not total:
        return 0.0
    return sum(len(s.text) for s in spans if s.font in wanted) / total
