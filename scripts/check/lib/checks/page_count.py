"""Rule: Part B-1 fits inside the page cap."""

from __future__ import annotations

from .._pymupdf import fitz
from ..model import FAIL, PASS, CheckResult

def check_page_count(doc: "fitz.Document", max_pages: int | None) -> CheckResult:
    """Check the page count against the limit, when one applies.

    Args:
        doc: An open PyMuPDF document.
        max_pages: The limit, or None when the document has no page limit.

    Returns:
        A :class:`CheckResult`; a passing result when no limit applies.
    """
    if max_pages is None:
        return CheckResult("Page limit", PASS, f"{doc.page_count} pages, no limit set")
    if doc.page_count > max_pages:
        return CheckResult(
            "Page limit",
            FAIL,
            f"{doc.page_count} pages exceeds the {max_pages}-page limit -- cut "
            f"{doc.page_count - max_pages} page(s). Excess pages are made "
            "INVISIBLE after the deadline, silently deleting content.",
        )
    spare = max_pages - doc.page_count
    note = "at the limit" if spare == 0 else f"{spare} page(s) to spare"
    return CheckResult("Page limit", PASS, f"{doc.page_count}/{max_pages} pages, {note}")
