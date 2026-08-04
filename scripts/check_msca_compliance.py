#!/usr/bin/env python3
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
    python scripts/check_msca_compliance.py _build/partB1.pdf --max-pages 10
    python scripts/check_msca_compliance.py _build/partB2.pdf --no-page-limit

Exit code:
    0 if every hard check passed, 1 otherwise. WARN checks never change it.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - environment problem, not logic
    sys.exit(
        "FATAL: PyMuPDF (fitz) is not installed, so compliance cannot be "
        "verified.\n"
        "  Fix: `pixi install` (pymupdf is pinned in pixi.toml), or "
        "`pip install pymupdf`.\n"
        "This is deliberately fatal rather than falling back to a partial "
        "poppler check: a checker that silently skips the margin, font-size "
        "and footer tests would exit 0 on exactly the kind of PDF it exists "
        "to catch."
    )

# --- constants -------------------------------------------------------------

PT_PER_MM = 72.0 / 25.4
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
A4_TOLERANCE_PT = 2.0

MIN_MARGIN_MM = 15.0
MIN_BODY_PT = 11.0
MIN_NON_BODY_PT = 8.0

# LaTeX's `11pt` class option sets \normalsize to 10.95pt, not 11.00pt, and
# PyMuPDF derives the size from the text matrix, so a correctly configured
# document reports 10.8-11.0pt. Testing `< 11.0` literally would fail every
# compliant render. 0.25pt is wide enough to absorb both effects and far too
# narrow to let a real 10pt or 10.5pt body through.
SIZE_TOLERANCE_PT = 0.25

FOOTER_RE = re.compile(r"Part B - Page (\d+) of (\d+)")

# Times New Roman and its metric-compatible free equivalents.
TIMES_RE = re.compile(r"TeXGyreTermes|NimbusRom|TimesNewRoman|Times|LiberationSerif", re.I)

# Hard-banned: these are what a bypassed template produces. Checked before the
# allow-lists, so a name matching both loses.
BANNED_RE = re.compile(
    r"LMRoman|LMSans|LMMono|LMMath|LatinModern|ComputerModern|^CM[A-Z]+\d", re.I
)

# Times-matched math companions from the newtx package. They carry the symbols
# (>=, ->, Greek) that no text font holds, and they are Times-metric by design.
# Without this allowance, one ">=" in the prose would fail an otherwise perfect
# document -- but note the alternative is worse: dropping newtx pulls in the
# Computer Modern math fonts, which BANNED_RE rejects on sight.
MATH_COMPANION_RE = re.compile(r"^(txsys|txexa|txmia|NewTX|ntx)", re.I)

# Superscript reference markers from the Nature CSL render at 8pt. They are
# reference markers, not body prose -- "text elements other than the body
# text ... may deviate" -- so digits-and-separators runs are allowed down to
# the 8pt floor. Anything else at 8pt is a genuine violation.
REF_MARKER_RE = re.compile(r"^[\d,\s‒-―-]+$")

CAPTION_RE = re.compile(r"^\s*(Table|Figure|Fig\.)\s*\d", re.I)

PLACEHOLDER_PATTERNS = (
    r"\[confirm",
    r"\[SEARCH DATE",
    r"TODO cite",
    r"\[CHECK\]",
    r"\[NOT FOUND",
    r"\*\*",
)

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


# --- text extraction helpers ----------------------------------------------


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


def iter_spans(doc: "fitz.Document") -> Iterator[Span]:
    """Yield every positioned text run in the document.

    Args:
        doc: An open PyMuPDF document.

    Yields:
        One :class:`Span` per styled run, in page then reading order.
    """
    for page_index, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            lines = block.get("lines", [])
            block_text = "".join(
                span["text"] for line in lines for span in line["spans"]
            )
            for line in lines:
                for span in line["spans"]:
                    yield Span(
                        page=page_index + 1,
                        text=span["text"],
                        font=strip_subset_prefix(span["font"]),
                        size=round(span["size"], 2),
                        bbox=tuple(span["bbox"]),  # type: ignore[arg-type]
                        block_text=block_text,
                    )


def strip_subset_prefix(font_name: str) -> str:
    """Remove the six-letter subset tag PDF writers prepend to font names.

    ``ZFRQFY+TeXGyreTermes-Bold`` becomes ``TeXGyreTermes-Bold``.

    Args:
        font_name: Font name exactly as recorded in the PDF.

    Returns:
        The font name without its subset prefix.
    """
    return font_name.split("+", 1)[-1]


def is_footer(span: Span) -> bool:
    """Report whether a span is part of the mandated page footer.

    Args:
        span: The span to classify.

    Returns:
        True if the span's text matches the ``Part B - Page X of Y`` footer.
    """
    return bool(FOOTER_RE.search(span.text) or FOOTER_RE.search(span.block_text))


def is_exempt_from_body_size(span: Span) -> tuple[bool, str]:
    """Decide whether a span may legitimately be smaller than 11 pt.

    The form allows "text elements other than the body text, such as headers,
    foot/end notes, captions, formulas, etc." down to 8 pt. Three concrete
    kinds occur in this document.

    Args:
        span: The span to classify.

    Returns:
        A ``(exempt, zone)`` pair; ``zone`` names the exemption or is empty.
    """
    if is_footer(span):
        return True, "footer"
    if CAPTION_RE.match(span.block_text):
        return True, "caption"
    if REF_MARKER_RE.match(span.text.strip()) and span.text.strip():
        return True, "reference marker"
    return False, ""


def body_bbox(page: "fitz.Page") -> "fitz.Rect | None":
    """Compute the bounding box of body text on a page, excluding the footer.

    The margin rule reads "not including any footers or headers", so the
    footer -- which sits by design in the bottom margin -- must be dropped
    before measuring, or every compliant page measures a ~6 mm bottom margin.

    Args:
        page: The page to measure.

    Returns:
        The union of all non-footer text bounding boxes, or None if the page
        has no body text.
    """
    box: "fitz.Rect | None" = None
    for block in page.get_text("dict")["blocks"]:
        lines = block.get("lines", [])
        text = "".join(s["text"] for line in lines for s in line["spans"])
        if FOOTER_RE.search(text):
            continue
        for line in lines:
            rect = fitz.Rect(line["bbox"])
            box = rect if box is None else (box | rect)
    return box


# --- hard checks -----------------------------------------------------------


def check_page_size(doc: "fitz.Document") -> CheckResult:
    """Check that every page is A4 within the allowed tolerance.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` naming any page that is not A4.
    """
    offenders = []
    for i, page in enumerate(doc, start=1):
        w, h = page.rect.width, page.rect.height
        if (
            abs(w - A4_WIDTH_PT) > A4_TOLERANCE_PT
            or abs(h - A4_HEIGHT_PT) > A4_TOLERANCE_PT
        ):
            offenders.append(f"p{i} {w:.1f}x{h:.1f}pt")
    if offenders:
        hint = " (US Letter is 612x792 -- check papersize/geometry in _quarto.yml)"
        return CheckResult(
            "A4 page size",
            FAIL,
            f"{len(offenders)} non-A4 page(s): {', '.join(offenders[:5])}{hint}",
        )
    return CheckResult(
        "A4 page size",
        PASS,
        f"all {doc.page_count} pages {A4_WIDTH_PT:.0f}x{A4_HEIGHT_PT:.0f}pt",
    )


def check_fonts(doc: "fitz.Document") -> CheckResult:
    """Check that every font is embedded and from a Times family.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` listing every offending font.
    """
    seen: dict[str, bool] = {}
    for page_index in range(doc.page_count):
        for xref, ext, _type, basefont, *_ in doc.get_page_fonts(page_index):
            seen[strip_subset_prefix(basefont)] = ext != "n/a"

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

    problems = []
    if banned:
        problems.append(
            f"Latin Modern / Computer Modern: {', '.join(banned)} "
            "(the template was bypassed -- see project.render in _quarto.yml)"
        )
    if foreign:
        problems.append(f"not a Times family: {', '.join(foreign)}")
    if unembedded:
        problems.append(f"not embedded: {', '.join(unembedded)}")
    if problems:
        return CheckResult("Times fonts, embedded", FAIL, "; ".join(problems))
    return CheckResult(
        "Times fonts, embedded",
        PASS,
        f"{len(allowed)} font(s), all embedded: {', '.join(allowed)}",
    )


def check_font_sizes(spans: Sequence[Span]) -> CheckResult:
    """Check that body text is at least 11 pt and exempt text at least 8 pt.

    Args:
        spans: Every positioned text run in the document.

    Returns:
        A :class:`CheckResult` carrying the size histogram, so borderline
        cases stay visible even when the check passes.
    """
    floor = MIN_BODY_PT - SIZE_TOLERANCE_PT
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


def check_margins(doc: "fitz.Document") -> CheckResult:
    """Check that body text keeps at least 15 mm clear on all four sides.

    Measured from the body-text bounding box, with the footer excluded as the
    rule requires.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` reporting the tightest margin found per side.
    """
    worst = {"top": 1e9, "right": 1e9, "bottom": 1e9, "left": 1e9}
    worst_page = dict.fromkeys(worst, 0)

    for i, page in enumerate(doc, start=1):
        box = body_bbox(page)
        if box is None:
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
        return CheckResult("Margins >= 15 mm", FAIL, "no text found in document")

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


def check_page_count(doc: "fitz.Document", max_pages: int | None) -> CheckResult:
    """Check the page count against the limit, when one applies.

    Args:
        doc: An open PyMuPDF document.
        max_pages: The limit, or None when the document has no page limit.

    Returns:
        A :class:`CheckResult`; a passing result when no limit applies.
    """
    if max_pages is None:
        return CheckResult("Page limit", PASS, f"{doc.page_count} pages, no limit set")
    if doc.page_count > max_pages:
        return CheckResult(
            "Page limit",
            FAIL,
            f"{doc.page_count} pages exceeds the {max_pages}-page limit -- cut "
            f"{doc.page_count - max_pages} page(s). Excess pages are made "
            "INVISIBLE after the deadline, silently deleting content.",
        )
    spare = max_pages - doc.page_count
    note = "at the limit" if spare == 0 else f"{spare} page(s) to spare"
    return CheckResult("Page limit", PASS, f"{doc.page_count}/{max_pages} pages, {note}")


def check_placeholders(doc: "fitz.Document") -> CheckResult:
    """Check that no unresolved authoring placeholder reached the PDF.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A :class:`CheckResult` quoting each placeholder found, with its page.
    """
    hits: list[str] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        for pattern in PLACEHOLDER_PATTERNS:
            for match in re.finditer(pattern + r".{0,45}", text, re.IGNORECASE | re.S):
                excerpt = " ".join(match.group(0).split())
                hits.append(f"p{i}: {excerpt!r}")
    if hits:
        return CheckResult(
            "No unresolved placeholders",
            FAIL,
            f"{len(hits)} found -- {' | '.join(hits[:5])}",
        )
    return CheckResult(
        "No unresolved placeholders",
        PASS,
        f"none of {len(PLACEHOLDER_PATTERNS)} patterns present",
    )


# --- warn checks -----------------------------------------------------------


def warn_cover_and_toc(doc: "fitz.Document") -> CheckResult:
    """Report a probable cover page or table of contents.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A WARN-level :class:`CheckResult`.
    """
    problems = []
    first_page = doc[0].get_text().strip()
    # A cover page carries almost no text; a real section 1 page is dense.
    if len(first_page) < 400:
        problems.append(f"page 1 holds only {len(first_page)} chars -- cover page?")
    for i, page in enumerate(doc, start=1):
        if re.search(r"table of contents", page.get_text(), re.IGNORECASE):
            problems.append(f"'Table of Contents' on p{i}")
    if problems:
        return CheckResult("No cover page / ToC", WARN, "; ".join(problems), hard=False)
    return CheckResult(
        "No cover page / ToC",
        PASS,
        "page 1 starts the body text; no 'Table of Contents' string",
        hard=False,
    )


def warn_reference_span(doc: "fitz.Document") -> CheckResult:
    """Report how much of the page budget the reference list consumes.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        A WARN-level :class:`CheckResult`, always informational.
    """
    # Find the "References" heading wherever it falls on its page — matching
    # only the top of a page misses the common case of the list starting
    # halfway down, and then silently reports "no reference list".
    start_page = start_y = None
    for i, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"]).strip()
                if text == "References":
                    start_page, start_y = i, line["bbox"][1]
                    break
            if start_page is not None:
                break
        if start_page is not None:
            break
    if start_page is None:
        return CheckResult("Reference-list span", PASS, "no reference list", hard=False)

    top = MIN_MARGIN_MM * PT_PER_MM
    bottom = doc[0].rect.y1 - MIN_MARGIN_MM * PT_PER_MM
    usable = bottom - top
    last = body_bbox(doc[doc.page_count - 1])
    end_fraction = ((last.y1 - top) / usable) if last else 1.0
    span = (doc.page_count - start_page - 1) + end_fraction - (start_y - top) / usable
    return CheckResult(
        "Reference-list span",
        PASS,
        f"~{span:.2f} pages (starts p{start_page + 1} of {doc.page_count})",
        hard=False,
    )


def warn_pdf_version(pdf_path: Path, doc: "fitz.Document") -> CheckResult:
    """Report the PDF version and producer for the Adobe v3+ requirement.

    Args:
        pdf_path: Path to the PDF, read directly for its version header.
        doc: An open PyMuPDF document, for the producer string.

    Returns:
        A WARN-level :class:`CheckResult`.
    """
    header = pdf_path.read_bytes()[:8].decode("latin-1", "replace")
    match = re.search(r"%PDF-(\d)\.(\d)", header)
    producer = doc.metadata.get("producer") or "unknown"
    if not match:
        return CheckResult(
            "PDF version (Adobe v3+)", WARN, f"unreadable header {header!r}", hard=False
        )
    major, minor = int(match.group(1)), int(match.group(2))
    # "Adobe version 3 or higher" means Acrobat 3, which writes PDF 1.2.
    ok = (major, minor) >= (1, 2)
    return CheckResult(
        "PDF version (Adobe v3+)",
        PASS if ok else WARN,
        f"PDF {major}.{minor}, producer {producer}",
        hard=False,
    )


# --- driver ----------------------------------------------------------------


def run_checks(pdf_path: Path, max_pages: int | None) -> list[CheckResult]:
    """Run every compliance check against one PDF.

    Args:
        pdf_path: Path to the rendered PDF.
        max_pages: Page limit, or None when the document has no limit.

    Returns:
        All check results, hard checks first.

    Raises:
        FileNotFoundError: If ``pdf_path`` does not exist.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with fitz.open(pdf_path) as doc:
        spans = list(iter_spans(doc))
        return [
            check_page_size(doc),
            check_fonts(doc),
            check_font_sizes(spans),
            check_margins(doc),
            check_footer(doc),
            check_page_count(doc, max_pages),
            check_placeholders(doc),
            warn_cover_and_toc(doc),
            warn_reference_span(doc),
            warn_pdf_version(pdf_path, doc),
        ]


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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--max-pages", type=int, help="page limit (Part B-1: 10)")
    group.add_argument(
        "--no-page-limit",
        action="store_true",
        help="document has no page limit (Part B-2)",
    )
    args = parser.parse_args(argv)

    max_pages = None if args.no_page_limit else args.max_pages
    results = run_checks(args.pdf, max_pages)
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
    if "--self-check" in sys.argv:
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
