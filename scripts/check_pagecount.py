#!/usr/bin/env python3
"""Fail the build if Part B-1 exceeds the MSCA page limit.

The MSCA-PF rules cap Part B-1 (Sections 1 + 2 + 3, including all tables,
figures and references) at 10 A4 pages. This guard reads the rendered PDF
and exits non-zero if the limit is exceeded, so an overflow is caught at
build time instead of at submission.

Usage:
    python scripts/check_pagecount.py <pdf_path> [limit]

Args:
    pdf_path: Path to the rendered Part B-1 PDF.
    limit:    Maximum allowed pages (default: 10).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def count_pdf_pages(pdf_path: Path) -> int:
    """Return the number of pages in a PDF.

    Prefers the ``pdfinfo`` CLI (poppler); falls back to ``pypdf`` if the
    CLI is not on the PATH.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        The page count as an integer.

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
        RuntimeError: If no page-counting backend is available.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if shutil.which("pdfinfo"):
        out = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
        raise RuntimeError("Could not parse page count from pdfinfo output.")

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Need either the 'pdfinfo' CLI (poppler) or the 'pypdf' package."
        ) from exc
    return len(PdfReader(str(pdf_path)).pages)


def main(argv: list[str]) -> int:
    """Check the PDF page count against the limit.

    Args:
        argv: Command-line arguments (excluding the program name).

    Returns:
        Process exit code: 0 if within the limit, 1 if exceeded.
    """
    if not argv:
        print("usage: check_pagecount.py <pdf_path> [limit]", file=sys.stderr)
        return 2

    pdf_path = Path(argv[0])
    limit = int(argv[1]) if len(argv) > 1 else 10

    pages = count_pdf_pages(pdf_path)
    margin = limit - pages

    if pages > limit:
        print(
            f"❌ PART B-1 OVER LIMIT: {pages} pages (limit {limit}). "
            f"Cut {pages - limit} page(s) before submitting.",
            file=sys.stderr,
        )
        return 1

    status = "✅"
    note = "at the limit" if margin == 0 else f"{margin} page(s) to spare"
    print(f"{status} Part B-1: {pages}/{limit} pages ({note}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
