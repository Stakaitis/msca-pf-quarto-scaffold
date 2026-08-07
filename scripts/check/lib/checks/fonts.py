"""Rule: body text is a Times family, and every font is embedded."""

from __future__ import annotations

import re
from typing import Sequence

from .._pymupdf import fitz
from ..extract import _font_char_share, strip_subset_prefix
from ..model import FAIL, PASS, WARN, CheckResult, Span
from ..rules import (BANNED_RE, FOREIGN_FONT_BODY_SHARE, MATH_COMPANION_RE,
                     TIMES_RE)

def check_fonts(doc: "fitz.Document", spans: Sequence[Span] = ()) -> CheckResult:
    """Check that every font is embedded and from a Times family.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` listing every offending font.
    """
    seen: dict[str, bool] = {}
    for page_index in range(doc.page_count):
        for xref, ext, _type, basefont, *_ in doc.get_page_fonts(page_index):
            # AND, not assignment: a font unembedded on one page must stay
            # unembedded even if a same-named embedded subset appears later.
            name_ = strip_subset_prefix(basefont)
            seen[name_] = seen.get(name_, True) and (ext != "n/a")

    banned, foreign, unembedded, allowed = [], [], [], []
    for name, embedded in sorted(seen.items()):
        if not embedded:
            unembedded.append(name)
        if BANNED_RE.search(name):
            banned.append(name)
        elif TIMES_RE.search(name) or MATH_COMPANION_RE.search(name):
            allowed.append(name)
        else:
            foreign.append(name)

    problems: list[str] = []
    notes: list[str] = []
    if banned:
        # Two very different causes produce a banned font, and the fix differs,
        # so name the likely one rather than always blaming the template.
        mono_only = all(re.search(r"Mono|Typewriter|CMTT", n, re.I) for n in banned)
        hint = (
            "a markdown code span (`like this`) renders in Latin Modern Mono -- "
            "remove the backticks; there is no Times monospace"
            if mono_only
            else "the template was bypassed -- see project.render in _quarto.yml"
        )
        problems.append(f"Latin Modern / Computer Modern: {', '.join(banned)} ({hint})")
    if foreign:
        # The rule is scoped: "The reference font for the BODY TEXT ... is Times
        # New Roman", and "text elements other than the body text ... may
        # deviate". A Gantt chart or figure carrying Helvetica is therefore
        # legal. What is never legal is the body itself in another face.
        #
        # Distinguish by share of characters: a figure's labels are a small
        # fraction of the document, a mis-set body is most of it. Latin Modern
        # stays a hard FAIL above regardless of share -- it is the signature of
        # a bypassed template, not a design choice.
        share = _font_char_share(spans, foreign)
        if share >= FOREIGN_FONT_BODY_SHARE:
            problems.append(
                f"not a Times family, and {share:.0%} of all characters: "
                f"{', '.join(foreign)} -- this is body text in the wrong face"
            )
        else:
            notes.append(
                f"non-Times face(s) on {share:.1%} of characters "
                f"({', '.join(foreign)}) -- allowed for figures and captions, "
                f"which the rules exempt; check it is not body text"
            )
    if unembedded:
        problems.append(f"not embedded: {', '.join(unembedded)}")
    if problems:
        return CheckResult("Times fonts, embedded", FAIL, "; ".join(problems))
    if notes:
        return CheckResult("Times fonts, embedded", WARN, "; ".join(notes), hard=False)
    return CheckResult(
        "Times fonts, embedded",
        PASS,
        f"{len(allowed)} font(s), all embedded: {', '.join(allowed)}",
    )
