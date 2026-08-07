"""Run every check against a document.

This module is the wiring: each rule lives in its own file and knows nothing
about the others, and the order they run in is declared here once. Adding a
rule means adding a module and one line below -- nothing else changes.

Order matters only for readability of the report, with one exception:
freshness runs first, because if the file is stale every number after it was
measured on the wrong document.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .._pymupdf import fitz
from ..extract import iter_spans
from ..model import CheckResult, FAIL
from .advisory import warn_cover_and_toc, warn_pdf_version, warn_reference_span
from .font_sizes import check_font_sizes
from .fonts import check_fonts
from .footer import check_footer
from .freshness import check_freshness
from .margins import check_margins
from .page_count import check_page_count
from .page_size import check_page_size
from .placeholders import check_placeholders
from .word import check_docx

__all__ = ["run_checks", "check_docx"]


def run_checks(pdf_path: Path, max_pages: int | None) -> list[CheckResult]:
    """Run every compliance check against one PDF.

    Args:
        pdf_path: Path to the rendered PDF.
        max_pages: Page limit, or None when the document has no limit.

    Returns:
        All check results, hard checks first.

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if pdf_path.suffix.lower() == ".docx":
        # Same rules, different container. The .docx has no page count until
        # Word lays it out, so --max-pages does not apply to it.
        return check_docx(pdf_path)

    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            # Truncated or interrupted render. Bail before the per-page checks,
            # which index page 0 and would raise IndexError, discarding every
            # result computed so far.
            return [
                CheckResult(
                    "Readable PDF", FAIL,
                    f"{pdf_path} contains 0 pages -- the file is truncated or "
                    "the render was interrupted; re-run `pixi run build`",
                )
            ]
        spans = list(iter_spans(doc))
        return [
            check_freshness(pdf_path),
            check_page_size(doc),
            check_fonts(doc, spans),
            check_font_sizes(spans, doc.page_count),
            check_margins(doc),
            check_footer(doc),
            check_page_count(doc, max_pages),
            check_placeholders(doc),
            warn_cover_and_toc(doc),
            warn_reference_span(doc),
            warn_pdf_version(pdf_path, doc),
        ]
