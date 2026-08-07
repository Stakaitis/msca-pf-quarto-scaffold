#!/usr/bin/env python3
"""Generate the Section 3 Gantt chart at MSCA-legal size.

Drives the vendored ``scripts/gantt/vendor/gantt.py`` with the settings this proposal
needs, and verifies the result against the two rules a figure can break.

WHY A WRAPPER: the chart tool defaults to a 1400 px canvas, which is 370 mm
wide. Quarto scales that down to the 178 mm text column, and scaling a vector
figure scales its TEXT too -- the 8.7 pt labels land at 4.2 pt, below the 8 pt
floor for non-body text and unreadable on paper. Generating at column width
instead means the label sizes you see are the label sizes that print.

The font is left as the tool's own. That is legal: the rules scope Times New
Roman to "the body text of proposals", and say text elements other than the
body text "may deviate, but must be legible and not be less than 8 points".
The compliance gate treats a non-Times face as a warning when it covers a small
share of the document, and a failure when it covers the body.

    pixi run gantt              # writes figures/gantt.pdf from gantt.yaml
    python scripts/gantt/make.py --check figures/gantt.pdf
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# A4 (210 mm) less the 16 mm margins set in _quarto.yml.
TEXT_COLUMN_MM = 210 - 2 * 16
PT_PER_MM = 72 / 25.4
PX_PER_PT = 1 / 0.75  # the chart tool's canvas is px; its PDF output is pt
MIN_NON_BODY_PT = 8.0
# A4 height less the 16 mm margins, less room for a caption. A figure taller
# than this overflows the text block and eats into the bottom margin -- which
# the compliance gate fails, correctly.
TEXT_BLOCK_MM = 297 - 2 * 16 - 12


def column_width_px() -> int:
    """Canvas width whose PDF output is exactly the text column.

    Returns:
        Width in pixels for the chart tool's ``STATIC_WIDTH``.
    """
    return round(TEXT_COLUMN_MM * PT_PER_MM * PX_PER_PT)


def generate(spec: Path, out_dir: Path, stem: str, title: str) -> Path:
    """Render the Gantt chart to a vector PDF at text-column width.

    Args:
        spec: YAML/CSV/JSON task list.
        out_dir: Directory to write into.
        stem: Output filename stem.
        title: Chart title.

    Returns:
        Path to the generated PDF.

    Raises:
        SystemExit: If the chart tool fails or writes no PDF.
    """
    here = Path(__file__).resolve().parent
    tool = here / "vendor" / "gantt.py"
    out_dir.mkdir(parents=True, exist_ok=True)

    # STATIC_WIDTH is a module constant, so set it by importing rather than
    # editing the vendored file (which would be lost on the next re-sync).
    driver = (
        f"import sys; sys.path.insert(0, {str(here / 'vendor')!r});"
        # plotly picks orjson when it is installed, and orjson cannot serialise
        # a pandas Timestamp -- the chart tool passes dates through as
        # Timestamps, so the export dies with "Type is not JSON serializable".
        # orjson arrives as a transitive conda dependency, so the environment
        # that has it is the reproducible one. Pin the encoder instead of
        # fighting the dependency graph.
        "from plotly.io._json import config as _pjc; _pjc.default_engine = 'json';"
        f"import gantt; gantt.STATIC_WIDTH = {column_width_px()};"
        f"sys.argv = ['gantt.py', {str(spec)!r}, '-o', {str(out_dir)!r},"
        f" '-n', {stem!r}, '-t', {title!r}, '--formats', 'pdf',"
        f" '--theme', 'white', '--palette', 'okabe-ito', '--font', 'serif'];"
        f"gantt.main()"
    )
    proc = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"gantt tool failed:\n{proc.stderr.strip()}")

    pdf = out_dir / f"{stem}.pdf"
    if not pdf.exists():  # the tool suffixes the theme when it emits both
        alt = out_dir / f"{stem}_white.pdf"
        if alt.exists():
            alt.replace(pdf)
    if not pdf.exists():
        sys.exit(f"gantt tool wrote no PDF to {out_dir}")
    return pdf


def check(pdf: Path) -> int:
    """Verify the figure fits the column and keeps its text above 8 pt.

    Args:
        pdf: The generated chart.

    Returns:
        0 if the figure is usable, 1 otherwise.
    """
    try:
        import fitz
    except ImportError:
        print("PyMuPDF not available; skipping figure check", file=sys.stderr)
        return 0

    with fitz.open(pdf) as doc:
        page = doc[0]
        width_mm = page.rect.width / PT_PER_MM
        sizes = sorted({
            round(s["size"], 1)
            for b in page.get_text("dict")["blocks"]
            for l in b.get("lines", [])
            for s in l["spans"]
            if s["text"].strip()
        })

    ok = True
    if width_mm > TEXT_COLUMN_MM + 1:
        print(f"FAIL width {width_mm:.0f} mm exceeds the {TEXT_COLUMN_MM} mm text "
              f"column; Quarto will scale it and shrink the labels below 8 pt")
        ok = False
    else:
        print(f"  width {width_mm:.0f} mm fits the {TEXT_COLUMN_MM} mm column")

    height_mm = 0.0
    with fitz.open(pdf) as doc:
        height_mm = doc[0].rect.height / PT_PER_MM
    if height_mm > TEXT_BLOCK_MM:
        rows_over = height_mm / TEXT_BLOCK_MM
        print(f"FAIL height {height_mm:.0f} mm exceeds the {TEXT_BLOCK_MM} mm text "
              f"block -- the figure overflows the bottom margin.")
        print(f"     It needs {rows_over:.2f} pages. Cut roughly "
              f"{(1 - TEXT_BLOCK_MM / height_mm) * 100:.0f}% of the rows, or keep "
              f"the work plan as a markdown table (cheaper on the page budget).")
        ok = False
    else:
        print(f"  height {height_mm:.0f} mm fits the {TEXT_BLOCK_MM} mm text block")

    if sizes and min(sizes) < MIN_NON_BODY_PT:
        print(f"FAIL smallest label {min(sizes)} pt is below the {MIN_NON_BODY_PT} pt "
              f"floor for non-body text")
        ok = False
    elif sizes:
        print(f"  labels {min(sizes)}-{max(sizes)} pt, all at or above "
              f"{MIN_NON_BODY_PT} pt")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    """Generate and check the Gantt chart.

    Args:
        argv: Command-line arguments excluding the program name.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", nargs="?", type=Path, default=Path("gantt.yaml"))
    ap.add_argument("-o", "--out-dir", type=Path, default=Path("figures"))
    ap.add_argument("-n", "--name", default="gantt")
    ap.add_argument("-t", "--title", default="")
    ap.add_argument("--check", type=Path, help="only check an existing PDF")
    args = ap.parse_args(argv)

    if args.check:
        return check(args.check)
    if not args.spec.exists():
        sys.exit(f"task list not found: {args.spec}")
    pdf = generate(args.spec, args.out_dir, args.name, args.title)
    print(f"wrote {pdf}")
    return check(pdf)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
