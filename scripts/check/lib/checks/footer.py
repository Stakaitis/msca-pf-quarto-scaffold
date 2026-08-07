"""Rule: every page carries the mandated footer."""

from __future__ import annotations

from .._pymupdf import fitz
from ..model import FAIL, PASS, CheckResult
from ..rules import FOOTER_RE

def check_footer(doc: "fitz.Document") -> CheckResult:
    """Check the mandated footer on every page, including its total.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` naming pages with a missing or wrong footer.
    """
    missing: list[int] = []
    wrong: list[str] = []
    for i, page in enumerate(doc, start=1):
        match = FOOTER_RE.search(page.get_text())
        if match is None:
            missing.append(i)
            continue
        shown_page, shown_total = int(match.group(1)), int(match.group(2))
        if shown_page != i:
            wrong.append(f"p{i} says 'Page {shown_page}'")
        if shown_total != doc.page_count:
            wrong.append(f"p{i} says 'of {shown_total}', real total {doc.page_count}")

    problems = []
    if missing:
        problems.append(
            f"no footer on page(s) {', '.join(map(str, missing[:8]))} "
            "(fancyhdr + lastpage missing -- template bypassed?)"
        )
    if wrong:
        problems.append("; ".join(wrong[:4]))
    if problems:
        return CheckResult("Footer 'Part B - Page X of Y'", FAIL, " | ".join(problems))
    return CheckResult(
        "Footer 'Part B - Page X of Y'",
        PASS,
        f"correct on all {doc.page_count} pages, total resolves to {doc.page_count}",
    )
