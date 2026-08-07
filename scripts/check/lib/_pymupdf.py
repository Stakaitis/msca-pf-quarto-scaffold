"""Import PyMuPDF, or fail loudly.

Kept in its own module so the refusal message exists exactly once, and so every
check module can say ``from .._pymupdf import fitz`` without repeating the
guard.

The failure is deliberately fatal rather than degrading to a partial poppler
check: a checker that silently skipped the margin, font-size and footer tests
would exit 0 on exactly the kind of PDF it exists to catch.
"""

from __future__ import annotations

import sys

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - environment problem, not logic
    sys.exit(
        "FATAL: PyMuPDF (fitz) is not installed, so compliance cannot be "
        "verified.\n"
        "  Fix: `pixi install` (pymupdf is pinned in pixi.toml), or "
        "`pip install pymupdf`."
    )

__all__ = ["fitz"]
