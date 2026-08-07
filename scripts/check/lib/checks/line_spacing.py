"""Rule: at least single line spacing, and standard character spacing.

The form requires "Standard character spacing and a minimum of single line
spacing ... This applies to the body text, including text in tables." Squeezing
the leading is the obvious way to win back a page once the font size is already
pinned at 11 pt, and unlike a font change it is invisible at a glance.

WHAT "SINGLE" MEANS. There is no single number, so this measures the ratio of
baseline-to-baseline distance over font size and fails only what no convention
could call single spacing:

    LaTeX \\normalsize at 11 pt   1.20   (13.2 pt on 11 pt)
    this project's header        1.24   (13.6 bp on 11 bp)
    Word, Times New Roman        ~1.15
    MIN_LINE_SPACING_RATIO       1.10   <- the floor enforced here

1.10 sits below every convention above and well above the ~1.0 that deliberate
compression produces, so it fails tampering without failing a legitimately
typeset document. It is a floor, not a target.

Character spacing is checked separately: PDF records inter-character tracking as
a horizontal scale on the text matrix, so a document that has been condensed to
fit reports a horizontal scale below 100%.
"""

from __future__ import annotations

import re
from statistics import median

from .._pymupdf import fitz
from ..model import FAIL, PASS, CheckResult
from ..rules import MIN_BODY_PT, MIN_LINE_SPACING_RATIO, SIZE_TOLERANCE_PT


def _body_line_ratios(doc: "fitz.Document") -> list[tuple[int, float, float]]:
    """Baseline-gap / font-size for consecutive body lines in the same block.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        ``(page, ratio, size)`` per measurable line pair.
    """
    out: list[tuple[int, float, float]] = []
    for pno, page in enumerate(doc, start=1):
        for block in page.get_text("dict").get("blocks", []):
            lines = block.get("lines", [])
            prev_y = prev_size = None
            for line in lines:
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    prev_y = prev_size = None      # a blank line ends the run
                    continue
                # the dominant size on this line, weighted by how much text it sets
                size = max(spans, key=lambda s: len(s["text"]))["size"]
                y = line["bbox"][3]                # bottom edge tracks the baseline
                if prev_y is not None and prev_size is not None:
                    gap = y - prev_y
                    # Only same-size runs of body text. A gap spanning a size change
                    # is a paragraph boundary, not leading, and would read as huge.
                    if (
                        gap > 0
                        and abs(size - prev_size) <= SIZE_TOLERANCE_PT
                        and size >= MIN_BODY_PT - SIZE_TOLERANCE_PT
                        and gap < size * 3            # drop paragraph/section breaks
                    ):
                        out.append((pno, gap / size, size))
                prev_y, prev_size = y, size
    return out


def check_line_spacing(doc: "fitz.Document") -> CheckResult:
    """Check that body text is set at no less than single line spacing.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` reporting the measured ratio.
    """
    ratios = _body_line_ratios(doc)
    if len(ratios) < 5:
        # Too little running text to measure -- a one-page abstract, or a document
        # that is all tables. Do not invent a failure from three samples.
        return CheckResult(
            "Line spacing >= single",
            PASS,
            f"not enough consecutive body lines to measure ({len(ratios)} pairs)",
        )

    med = median(r for _, r, _ in ratios)
    tight = [(p, r) for p, r, _ in ratios if r < MIN_LINE_SPACING_RATIO]

    # A handful of tight pairs is normal: a line with no descenders sits closer.
    # A systematically compressed document moves the median, so judge on that and
    # report the outliers only as supporting evidence.
    if med < MIN_LINE_SPACING_RATIO:
        pages = sorted({p for p, _ in tight})[:5]
        return CheckResult(
            "Line spacing >= single",
            FAIL,
            f"median leading {med:.2f}x font size, below the {MIN_LINE_SPACING_RATIO:.2f}x "
            f"floor -- {len(tight)}/{len(ratios)} line pairs tight, p"
            f"{', p'.join(str(p) for p in pages)}. The form requires at least single "
            f"spacing; check for \\linespread or \\baselineskip in tex/msca-header.tex.",
        )
    return CheckResult(
        "Line spacing >= single",
        PASS,
        f"median leading {med:.2f}x font size over {len(ratios)} line pairs "
        f"(floor {MIN_LINE_SPACING_RATIO:.2f}x)",
    )


def check_char_spacing(doc: "fitz.Document") -> CheckResult:
    """Check that no text is condensed or tracked tighter than standard.

    Reads the operators rather than guessing from glyph widths. PDF sets
    horizontal scaling with ``Tz`` (100 = normal) and inter-character tracking
    with ``Tc`` (0 = normal), so condensed text is stated outright in the content
    stream. An earlier version inferred it from average character width and
    failed a perfectly normal document: a run of narrow glyphs in a table cell
    averages under 3 pt/char at 11 pt, which is indistinguishable from real
    condensing by width alone.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` naming any page with non-standard spacing.
    """
    offenders = []
    for pno, page in enumerate(doc, start=1):
        try:
            content = page.read_contents()
        except Exception:                       # pragma: no cover - malformed stream
            continue
        for raw, op in re.findall(rb"(-?[\d.]+)\s+(Tz|Tc)\b", content):
            try:
                val = float(raw)
            except ValueError:
                continue
            if op == b"Tz" and val < 99.5:
                offenders.append(f"p{pno} horizontal scale {val:g}%")
            elif op == b"Tc" and val < -0.01:
                offenders.append(f"p{pno} tracking {val:g}")
    if offenders:
        uniq = list(dict.fromkeys(offenders))
        return CheckResult(
            "Standard character spacing",
            FAIL,
            f"non-standard character spacing on {len(uniq)} page(s): "
            f"{', '.join(uniq[:5])} -- the form requires standard character spacing",
        )
    return CheckResult(
        "Standard character spacing", PASS,
        "no horizontal scaling or negative tracking in any content stream",
    )
