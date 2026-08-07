"""Rule: at least 15 mm clear on all four sides."""

from __future__ import annotations

from .._pymupdf import fitz
from ..extract import body_bbox
from ..model import FAIL, PASS, CheckResult
from ..rules import MIN_MARGIN_MM, PT_PER_MM

def check_margins(doc: "fitz.Document") -> CheckResult:
    """Check that body text keeps at least 15 mm clear on all four sides.

    Measured from the body-text bounding box, with the footer excluded as the
    rule requires.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` reporting the tightest margin found per side.
    """
    unmeasurable: list[int] = []
    worst = {"top": 1e9, "right": 1e9, "bottom": 1e9, "left": 1e9}
    worst_page = dict.fromkeys(worst, 0)

    for i, page in enumerate(doc, start=1):
        box = body_bbox(page)
        if box is None:
            # A page we cannot measure is UNVERIFIED, not compliant. Skipping it
            # is how a fully rasterised page used to sail through: its only text
            # was the footer, so it contributed nothing and the check passed on
            # the other pages' numbers.
            unmeasurable.append(i)
            continue
        rect = page.rect
        measured = {
            "top": box.y0,
            "right": rect.width - box.x1,
            "bottom": rect.height - box.y1,
            "left": box.x0,
        }
        for side, value_pt in measured.items():
            value_mm = value_pt / PT_PER_MM
            if value_mm < worst[side]:
                worst[side], worst_page[side] = value_mm, i

    if worst["top"] > 1e8:
        return CheckResult("Margins >= 15 mm", FAIL, "no measurable content in document")
    if unmeasurable:
        pages = ", ".join(f"p{n}" for n in unmeasurable[:6])
        return CheckResult(
            "Margins >= 15 mm",
            FAIL,
            f"{len(unmeasurable)} page(s) carry no measurable body content "
            f"({pages}) -- margins cannot be verified, so this is not a pass",
        )

    summary = ", ".join(
        f"{side} {worst[side]:.1f}mm (p{worst_page[side]})" for side in worst
    )
    breaches = [s for s, v in worst.items() if v < MIN_MARGIN_MM]
    if breaches:
        return CheckResult(
            "Margins >= 15 mm",
            FAIL,
            f"below 15mm on: {', '.join(breaches)} | measured minima: {summary}",
        )
    return CheckResult("Margins >= 15 mm", PASS, f"measured minima: {summary}")
