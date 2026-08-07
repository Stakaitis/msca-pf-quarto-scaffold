"""Checks that report but never fail the build."""

from __future__ import annotations
from ..extract import (body_bbox)

import re
from pathlib import Path

from .._pymupdf import fitz
from ..model import PASS, WARN, CheckResult
from ..rules import (MIN_MARGIN_MM, PT_PER_MM)

def warn_cover_and_toc(doc: "fitz.Document") -> CheckResult:
    """Report a probable cover page or table of contents.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A WARN-level :class:`CheckResult`.
    """
    problems = []
    first_page = doc[0].get_text().strip()
    # A cover page carries almost no text; a real section 1 page is dense.
    if len(first_page) < 400:
        problems.append(f"page 1 holds only {len(first_page)} chars -- cover page?")
    for i, page in enumerate(doc, start=1):
        if re.search(r"table of contents", page.get_text(), re.IGNORECASE):
            problems.append(f"'Table of Contents' on p{i}")
    if problems:
        return CheckResult("No cover page / ToC", WARN, "; ".join(problems), hard=False)
    return CheckResult(
        "No cover page / ToC",
        PASS,
        "page 1 starts the body text; no 'Table of Contents' string",
        hard=False,
    )


def warn_reference_span(doc: "fitz.Document") -> CheckResult:
    """Report how much of the page budget the reference list consumes.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A WARN-level :class:`CheckResult`, always informational.
    """
    # Find the "References" heading wherever it falls on its page — matching
    # only the top of a page misses the common case of the list starting
    # halfway down, and then silently reports "no reference list".
    start_page = start_y = None
    for i, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if text == "References":
                    start_page, start_y = i, line["bbox"][1]
                    break
            if start_page is not None:
                break
        if start_page is not None:
            break
    if start_page is None:
        return CheckResult("Reference-list span", PASS, "no reference list", hard=False)

    top = MIN_MARGIN_MM * PT_PER_MM
    bottom = doc[0].rect.y1 - MIN_MARGIN_MM * PT_PER_MM
    usable = bottom - top
    last = body_bbox(doc[doc.page_count - 1])
    end_fraction = ((last.y1 - top) / usable) if last else 1.0
    span = (doc.page_count - start_page - 1) + end_fraction - (start_y - top) / usable
    return CheckResult(
        "Reference-list span",
        PASS,
        f"~{span:.2f} pages (starts p{start_page + 1} of {doc.page_count})",
        hard=False,
    )


def warn_pdf_version(pdf_path: Path, doc: "fitz.Document") -> CheckResult:
    """Report the PDF version and producer for the Adobe v3+ requirement.

    Args:
        pdf_path: Path to the PDF, read directly for its version header.
        doc: An open PyMuPDF document, for the producer string.

    Returns:
        A WARN-level :class:`CheckResult`.
    """
    header = pdf_path.read_bytes()[:8].decode("latin-1", "replace")
    match = re.search(r"%PDF-(\d)\.(\d)", header)
    producer = doc.metadata.get("producer") or "unknown"
    if not match:
        return CheckResult(
            "PDF version (Adobe v3+)", WARN, f"unreadable header {header!r}", hard=False
        )
    major, minor = int(match.group(1)), int(match.group(2))
    # "Adobe version 3 or higher" means Acrobat 3, which writes PDF 1.2.
    ok = (major, minor) >= (1, 2)
    return CheckResult(
        "PDF version (Adobe v3+)",
        PASS if ok else WARN,
        f"PDF {major}.{minor}, producer {producer}",
        hard=False,
    )
