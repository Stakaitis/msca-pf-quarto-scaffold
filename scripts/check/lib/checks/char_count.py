"""Rule: the proposal summary fits the portal's character limit.

NOT a Part B rule. The summary lives in **Part A**, the online form in the
Funding & Tenders Portal, which caps it at 2000 characters. It is checked here
because it is the one limit in the whole application with no local warning: the
portal silently truncates or refuses on paste, at submission time, which is the
worst possible moment to discover the text is 263 characters too long.

Counted the way the portal counts: characters including spaces, excluding the
page footer and the document's own title, since neither is pasted into the form.
"""

from __future__ import annotations

from ..model import FAIL, PASS, CheckResult
from ..rules import ABSTRACT_MAX_CHARS, FOOTER_RE


def _submittable_text(doc: "fitz.Document") -> str:
    """The text an applicant would actually paste into the portal field.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        The document text without footers or a leading title line.
    """
    lines: list[str] = []
    for page in doc:
        for raw in page.get_text().splitlines():
            line = raw.strip()
            if not line or FOOTER_RE.search(line):
                continue
            lines.append(line)
    # Drop a bare title line ("Abstract", "Summary"): it labels the field, it is
    # not part of what goes in it.
    if lines and lines[0].lower() in {"abstract", "summary", "proposal summary"}:
        lines = lines[1:]
    return " ".join(lines)


def check_char_count(doc: "fitz.Document", max_chars: int | None) -> CheckResult:
    """Check the summary against the portal's character cap.

    Args:
        doc: An open PyMuPDF document.
        max_chars: The cap, or None for documents this does not apply to.

    Returns:
        A :class:`CheckResult` reporting the count against the cap.
    """
    if max_chars is None:
        return CheckResult(
            "Summary character count", PASS,
            "not a summary document -- no character cap applies", hard=False,
        )
    text = _submittable_text(doc)
    n = len(text)
    if n > max_chars:
        return CheckResult(
            "Summary character count",
            FAIL,
            f"{n} characters, {n - max_chars} over the {max_chars} cap. Part A of "
            f"the portal will not accept it. Cut {n - max_chars} characters "
            f"(roughly {round((n - max_chars) / 6)} words).",
        )
    return CheckResult(
        "Summary character count",
        PASS,
        f"{n}/{max_chars} characters, {max_chars - n} spare",
    )


__all__ = ["check_char_count", "ABSTRACT_MAX_CHARS"]
