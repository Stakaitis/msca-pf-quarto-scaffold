"""Data carried between extraction and the checks."""

from __future__ import annotations

from dataclasses import dataclass

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single compliance check.

    Attributes:
        name: Short human-readable name of the check.
        status: One of ``PASS``, ``FAIL`` or ``WARN``.
        detail: Measured evidence, phrased so a failure says what to change.
        hard: Whether a ``FAIL`` here must fail the build.
    """

    name: str
    status: str
    detail: str
    hard: bool = True

@dataclass(frozen=True)
class Span:
    """One run of text with a single font and size, positioned on a page.

    Attributes:
        page: 1-indexed page number.
        text: The literal text of the run.
        font: Font name as embedded, subset prefix already stripped.
        size: Rendered size in points.
        bbox: ``(x0, y0, x1, y1)`` in PDF points, origin top-left.
        block_text: Full text of the enclosing block, for caption detection.
    """

    page: int
    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]
    block_text: str
