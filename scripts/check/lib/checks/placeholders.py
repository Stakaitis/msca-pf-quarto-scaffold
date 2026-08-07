"""Project rule: no unreplaced placeholder reaches the reader."""

from __future__ import annotations

import re

from .._pymupdf import fitz
from ..model import FAIL, PASS, CheckResult
from ..rules import PLACEHOLDER_PATTERNS

def check_placeholders(doc: "fitz.Document") -> CheckResult:
    """Check that no unresolved authoring placeholder reached the PDF.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` quoting each placeholder found, with its page.
    """
    hits: list[str] = []
    for i, page in enumerate(doc, start=1):
        # Normalise whitespace first: PDF text extraction breaks a run at the
        # line end, so "[confirm the\nfacility]" would otherwise evade a
        # literal-space pattern entirely.
        text = re.sub(r"\s+", " ", page.get_text())
        for pattern in PLACEHOLDER_PATTERNS:
            for match in re.finditer(pattern + r".{0,45}", text, re.IGNORECASE | re.S):
                excerpt = " ".join(match.group(0).split())
                hits.append(f"p{i}: {excerpt!r}")
    if hits:
        return CheckResult(
            "No unresolved placeholders",
            FAIL,
            f"{len(hits)} found -- {' | '.join(hits[:5])}",
        )
    return CheckResult(
        "No unresolved placeholders",
        PASS,
        f"none of {len(PLACEHOLDER_PATTERNS)} patterns present",
    )
