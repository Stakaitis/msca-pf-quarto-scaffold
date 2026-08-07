"""Rule: the page size is A4."""

from __future__ import annotations

from .._pymupdf import fitz
from ..model import FAIL, PASS, CheckResult
from ..rules import A4_HEIGHT_PT, A4_TOLERANCE_PT, A4_WIDTH_PT

def check_page_size(doc: "fitz.Document") -> CheckResult:
    """Check that every page is A4 within the allowed tolerance.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` naming any page that is not A4.
    """
    offenders = []
    for i, page in enumerate(doc, start=1):
        w, h = page.rect.width, page.rect.height
        if (
            abs(w - A4_WIDTH_PT) > A4_TOLERANCE_PT
            or abs(h - A4_HEIGHT_PT) > A4_TOLERANCE_PT
        ):
            offenders.append(f"p{i} {w:.1f}x{h:.1f}pt")
    if offenders:
        hint = " (US Letter is 612x792 -- check papersize/geometry in _quarto.yml)"
        return CheckResult(
            "A4 page size",
            FAIL,
            f"{len(offenders)} non-A4 page(s): {', '.join(offenders[:5])}{hint}",
        )
    return CheckResult(
        "A4 page size",
        PASS,
        f"all {doc.page_count} pages {A4_WIDTH_PT:.0f}x{A4_HEIGHT_PT:.0f}pt",
    )
