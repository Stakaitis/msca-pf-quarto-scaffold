"""Rule: body text is at least 11 pt; other text at least 8 pt."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from ..extract import is_exempt_from_body_size
from ..model import FAIL, PASS, CheckResult, Span
from ..rules import MIN_BODY_PT, MIN_NON_BODY_PT, SIZE_TOLERANCE_PT

def check_font_sizes(spans: Sequence[Span], page_count: int = 0) -> CheckResult:
    """Check that body text is at least 11 pt and exempt text at least 8 pt.

    Args:
        spans: Every positioned text run in the document.

    Returns:
        A :class:`CheckResult` carrying the size histogram, so borderline
        cases stay visible even when the check passes.
    """
    floor = MIN_BODY_PT - SIZE_TOLERANCE_PT
    inspected = [s for s in spans if s.text.strip()]
    spans = inspected
    body_offenders: list[str] = []
    small_offenders: list[str] = []
    histogram: Counter[float] = Counter()

    for span in spans:
        if not span.text.strip():
            continue
        # Bucket to 0.1pt for display: PyMuPDF derives the size from the text
        # matrix, so a single 10.95pt paragraph otherwise reports as a dozen
        # distinct sizes and buries the one line that actually matters.
        histogram[round(span.size, 1)] += len(span.text)
        exempt, zone = is_exempt_from_body_size(span)
        if exempt:
            if span.size < MIN_NON_BODY_PT - SIZE_TOLERANCE_PT:
                small_offenders.append(
                    f"p{span.page} {span.size}pt ({zone}) {span.text.strip()[:30]!r}"
                )
        elif span.size < floor:
            body_offenders.append(
                f"p{span.page} {span.size}pt {span.text.strip()[:30]!r}"
            )

    hist = ", ".join(f"{size}pt:{count}ch" for size, count in sorted(histogram.items()))

    # Absence of offenders only means something if we actually inspected text.
    # A rasterised page yields no spans, so every size rule was vacuously
    # satisfied -- which used to report PASS on a page of 7pt scanned table.
    if not histogram:
        return CheckResult(
            "Font size >= 11 pt", FAIL,
            "no text spans found -- nothing could be measured, so this is not a pass",
        )
    pages_seen = {s.page for s in inspected}
    missing = [n for n in range(1, page_count + 1) if n not in pages_seen]
    if missing:
        return CheckResult(
            "Font size >= 11 pt", FAIL,
            f"{len(missing)} page(s) contain no measurable text "
            f"({', '.join(f'p{n}' for n in missing[:6])}) -- font size unverified "
            f"there | histogram: {hist}",
        )
    if body_offenders:
        return CheckResult(
            "Font size >= 11 pt",
            FAIL,
            f"{len(body_offenders)} body run(s) below {floor}pt: "
            f"{'; '.join(body_offenders[:4])} | histogram: {hist}",
        )
    if small_offenders:
        return CheckResult(
            "Font size >= 11 pt",
            FAIL,
            f"{len(small_offenders)} exempt run(s) below the 8pt floor: "
            f"{'; '.join(small_offenders[:4])} | histogram: {hist}",
        )
    return CheckResult("Font size >= 11 pt", PASS, f"histogram: {hist}")
