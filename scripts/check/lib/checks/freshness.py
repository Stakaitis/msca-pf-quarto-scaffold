"""Project rule: the output must be newer than every source.

A failed render leaves the previous file in place, and every other check
would then measure a document that was never rebuilt."""

from __future__ import annotations

from pathlib import Path

from ..model import FAIL, PASS, WARN, CheckResult
from ..rules import SOURCE_GLOBS

def check_freshness(pdf_path: Path) -> CheckResult:
    """Check the PDF is newer than every source it is built from.

    A failed `quarto render` leaves the previous PDF in place, untouched and
    perfectly valid-looking. Every other check in this file would then measure
    the OLD document and report a clean bill of health for a build that did not
    happen -- which has already nearly caused numbers from a stale render to be
    reported as current.

    Args:
        pdf_path: Path to the rendered PDF.

    Returns:
        FAIL if any source is newer than the PDF; WARN if the project directory
        cannot be located; PASS otherwise.
    """
    project = pdf_path.parent.parent if pdf_path.parent.name == "_build" else pdf_path.parent
    sources: list[Path] = []
    for pattern in SOURCE_GLOBS:
        sources.extend(project.glob(pattern))
    if not sources:
        return CheckResult(
            "Output is current", WARN,
            f"no source files found under {project} -- freshness unverified",
            hard=False,
        )

    pdf_mtime = pdf_path.stat().st_mtime
    newer = sorted(
        (p for p in sources if p.stat().st_mtime > pdf_mtime),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if newer:
        names = ", ".join(p.name for p in newer[:4])
        return CheckResult(
            "Output is current", FAIL,
            f"{len(newer)} source(s) are newer than this PDF ({names}) -- the "
            f"render did not happen or it failed. Re-run `pixi run build`; do "
            f"not trust any number measured from this file",
        )
    return CheckResult(
        "Output is current", PASS,
        f"newer than all {len(sources)} source file(s)",
    )
