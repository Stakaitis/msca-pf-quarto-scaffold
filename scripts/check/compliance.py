"""Validate a rendered Part B PDF against the MSCA-PF formatting rules.

The rules are quoted verbatim from the official application form (HE MSCA PF
V5.0, 27.03.2026), "Instructions for Drafting Part B of the Proposal":

    * "The page size is A4, and all margins (top, bottom, left, right) should
      be at least 15 mm (not including any footers or headers)."
    * "The reference font for the body text of proposals is Times New Roman
      (Windows platforms), Times/Times New Roman (Apple platforms) or Nimbus
      Roman No. 9 L (Linux distributions)."
    * "The minimum font size allowed is 11 points. Standard character spacing
      and a minimum of single line spacing is to be used. This applies to the
      body text, including text in tables."
    * "Text elements other than the body text, such as headers, foot/end
      notes, captions, formulas, etc. may deviate, but must be legible and not
      be less than 8 points."
    * "Sections 1, 2 and 3 together should not be longer than 10 pages."
    * "[proposals must be] in PDF format (Adobe version 3 or higher, with
      embedded fonts)."

This exists because formatting was eyeballed once and regressed: on
2026-07-28 a render came out US Letter, in Latin Modern, with no page footer,
because the .qmd was missing from `project.render` in _quarto.yml and so never
saw the tuned template. Nothing about that PDF looked wrong at a glance.

Usage:
    python scripts/check/compliance.py _build/partB1.pdf --part-b1
    python scripts/check/compliance.py _build/partB2.pdf --no-page-limit

Exit code:
    0 if every hard check passed, 1 otherwise. WARN checks never change it.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.checks import run_checks
from lib.model import FAIL, PASS, WARN, CheckResult, Span
from lib.rules import (BANNED_RE, CAPTION_RE, FOOTER_RE, MATH_COMPANION_RE,
                       PART_B1_PAGE_LIMIT, PT_PER_MM, REF_MARKER_RE,
                       TIMES_RE)


def print_report(pdf_path: Path, results: Iterable[CheckResult]) -> None:
    """Print the results as a readable table.

    Args:
        pdf_path: Path to the PDF the results describe.
        results: The check results to print.
    """
    icon = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN"}
    print(f"\nMSCA formatting compliance — {pdf_path}")
    print("-" * 78)
    for result in results:
        kind = "hard" if result.hard else "warn"
        print(f"  [{icon[result.status]}] {result.name:<28} ({kind})")
        print(f"         {result.detail}")
    print("-" * 78)


def main(argv: Sequence[str] | None = None) -> int:
    """Check one PDF and return a process exit code.

    Args:
        argv: Command-line arguments excluding the program name; defaults to
            ``sys.argv[1:]``.

    Returns:
        0 if every hard check passed, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Validate a Part B PDF against the MSCA-PF formatting rules.",
    )
    parser.add_argument("pdf", type=Path, help="path to the rendered PDF")
    # Required, and mutually exclusive on purpose: there is no default. Every
    # caller must state which page regime applies, so a limit can never be
    # dropped by forgetting a flag.
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--part-b1",
        action="store_true",
        help=f"apply the official Part B-1 cap ({PART_B1_PAGE_LIMIT} pages)",
    )
    group.add_argument("--max-pages", type=int, help="an explicit page limit")
    group.add_argument(
        "--no-page-limit",
        action="store_true",
        help="document has no page limit (Part B-2)",
    )
    args = parser.parse_args(argv)

    if args.part_b1:
        max_pages: int | None = PART_B1_PAGE_LIMIT
    elif args.no_page_limit:
        max_pages = None
    else:
        max_pages = args.max_pages

    # A PDF that cannot be read is not a compliance failure, it is a broken
    # input -- exit 2 so callers can tell the two apart. Without this the user
    # gets a raw traceback, which reads as "the checker is broken" rather than
    # "the file you pointed me at is".
    try:
        results = run_checks(args.pdf, max_pages)
    except FileNotFoundError as exc:
        print(f"CANNOT CHECK: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:  # fitz raises these for corrupt/empty/encrypted
        print(
            f"CANNOT CHECK: {args.pdf} is not a readable PDF ({exc}).\n"
            "  Re-render it with `pixi run build`.",
            file=sys.stderr,
        )
        return 2
    print_report(args.pdf, results)

    failures = [r for r in results if r.hard and r.status == FAIL]
    warnings = [r for r in results if not r.hard and r.status == WARN]
    if failures:
        print(
            f"NOT COMPLIANT: {len(failures)} hard check(s) failed "
            f"({', '.join(r.name for r in failures)}). Do not submit this PDF.\n"
        )
        return 1
    print(
        f"COMPLIANT: all {sum(1 for r in results if r.hard)} hard checks passed"
        + (f", {len(warnings)} warning(s) to review.\n" if warnings else ".\n")
    )
    return 0


def _self_check() -> None:
    """Assert the classifier rules that decide PASS from FAIL.

    These are the rules that would silently let a bad PDF through if they
    drifted, so they are asserted rather than trusted.
    """
    assert BANNED_RE.search("LMSans10-Bold")
    assert BANNED_RE.search("LMRoman10-Regular")
    assert BANNED_RE.search("LMMathSymbols10-Regular")
    assert BANNED_RE.search("CMR10") and BANNED_RE.search("CMSY10")
    assert not BANNED_RE.search("TeXGyreTermes-Bold")
    assert TIMES_RE.search("TeXGyreTermes-Italic")
    assert TIMES_RE.search("NimbusRomNo9L-Regu")
    assert TIMES_RE.search("TimesNewRomanPSMT")
    assert MATH_COMPANION_RE.search("txsys") and MATH_COMPANION_RE.search("NewTXMI")
    assert not MATH_COMPANION_RE.search("LMSans10")
    # A Latin Modern name must lose even though "LMMath" also looks math-ish.
    assert BANNED_RE.search("LMMathSymbols10-Regular")

    m = FOOTER_RE.search("Part B - Page 7 of 9")
    assert m and (m.group(1), m.group(2)) == ("7", "9")
    assert not FOOTER_RE.search("Part B — Page 7 of 9")  # en dash is not the footer

    assert REF_MARKER_RE.match("1,2") and REF_MARKER_RE.match("13")
    assert not REF_MARKER_RE.match("wordlike")
    assert CAPTION_RE.match("Table 1: work packages")
    assert not CAPTION_RE.match("Tables are hard")

    assert abs(15.0 * PT_PER_MM - 42.52) < 0.01
    print("self-check: all classifier assertions hold")


if __name__ == "__main__":
    # --self-check runs the classifier assertions and nothing else. It must be
    # the ONLY argument: sniffing for it anywhere in argv meant a trailing
    # --self-check exiting 0 without ever opening the PDF -- a one-flag bypass
    # of the entire gate.
    if "--self-check" in sys.argv[1:]:
        if sys.argv[1:] != ["--self-check"]:
            raise SystemExit(
                "--self-check runs the internal assertions only and takes no "
                "other arguments."
            )
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
