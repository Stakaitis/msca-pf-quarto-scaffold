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
    python scripts/check_msca_compliance.py _build/partB1.pdf --part-b1
    python scripts/check_msca_compliance.py _build/partB2.pdf --no-page-limit

Exit code:
    0 if every hard check passed, 1 otherwise. WARN checks never change it.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
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

# "Sections 1, 2 and 3 together should not be longer than 10 pages."
# THE single definition of the cap. Callers pass --part-b1 rather than
# repeating the number, so pixi.toml, the Makefile and check_all.sh cannot
# drift apart from each other or from this file.
PART_B1_PAGE_LIMIT = 10

# This used to be 0.25pt, to absorb two defects that are now fixed at source in
# tex/msca-header.tex: LaTeX's `11pt` class option resolving to 10.95pt, and
# microtype font expansion smearing each line by +/-1.5%. Both are gone -- the
# body is declared in `bp` (1/72in, the PDF's own unit) and expansion is off, so
# the PDF now reports a clean 11.0.
#
# Keep this tight. It exists only to absorb float noise in the size PyMuPDF
# derives from the text matrix, NOT to forgive a document that is genuinely
# under-size. Widening it back to 0.25 would silently re-admit a 10.8pt render,
# which is exactly what an evaluator measuring in Acrobat would fail us on.
SIZE_TOLERANCE_PT = 0.02

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
# ^tx / ^ntx covers every newtx companion (txsys, txsym, txexa, txmia, ...).
# Narrower lists have bitten us: typing a tick pulled in txsym and hard-failed
# an otherwise perfect document. BANNED_RE is tested first, so widening here
# cannot admit a Latin Modern face.
MATH_COMPANION_RE = re.compile(r"^(tx|ntx|NewTX)", re.I)

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
    r"\[ACRONYM",
    r"\*\*",
    # Catch-all for the bracketed-prompt style: [what], [co-author], [title],
    # [concrete fallback]. Ten of these were rendering into Part B-2 while the
    # gate reported "no unresolved placeholders", because every pattern above
    # names a specific marker. Lowercase-initial only, so numeric citation
    # markers and bracketed proper nouns are not swept up.
    r"\[[a-z][^\]\n]{0,80}\]",
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
        # Rectangles of every placed image, so text drawn over one can be
        # recognised as figure content rather than body prose.
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
    if not (TIMES_RE.search(span.font) or MATH_COMPANION_RE.search(span.font)):
        # Not set in the body face, so by the rules' own definition it is not
        # body text: "the reference font for the BODY TEXT ... is Times New
        # Roman". Figure labels and chart axes arrive in the chart tool's font
        # and are allowed down to the 8 pt floor, which is still enforced below.
        #
        # This cannot be used to smuggle in an under-size body: if a non-Times
        # face covers a meaningful share of the document, check_fonts fails it
        # outright. Geometry was tried first and rejected -- a vector figure is
        # a Form XObject whose reported bbox is in its own coordinate space, not
        # the page's, so intersection tests silently measured the wrong region.
        return True, "non-body face (figure/caption)"
    return False, ""


def body_bbox(page: "fitz.Page") -> "fitz.Rect | None":
    """Compute the bounding box of body text on a page, excluding the footer.

    The margin rule reads "not including any footers or headers", so the
    footer -- which sits by design in the bottom margin -- must be dropped
    before measuring, or every compliant page measures a ~6 mm bottom margin.

    Args:
        page: The page to measure.

    Images and vector graphics are measured too. They used to be invisible
    here, because only text blocks carry a "lines" key -- which meant a Quarto
    figure wider than the text column (`![](g.png){width=190mm}` against a
    178 mm column) sat 4 mm from the paper edge while this function still
    reported a 16 mm margin. A Gantt chart is expected in Section 3, so that
    blind spot was one figure away from going live.

    Args:
        page: The page to measure.

    Returns:
        The union of all non-footer body geometry, or None if the page carries
        nothing measurable at all.
    """
    box: "fitz.Rect | None" = None

    def add(rect: "fitz.Rect") -> None:
        nonlocal box
        if rect.is_empty or rect.is_infinite:
            return
        box = rect if box is None else (box | rect)

    for block in page.get_text("dict")["blocks"]:
        lines = block.get("lines", [])
        text = "".join(s["text"] for line in lines for s in line["spans"])
        if FOOTER_RE.search(text):
            continue
        for line in lines:
            add(fitz.Rect(line["bbox"]))

    # Raster images: block type 1 in the dict, but get_image_rects is the
    # reliable accessor for their placed rectangle.
    for img in page.get_images(full=True):
        for rect in page.get_image_rects(img[0]):
            add(fitz.Rect(rect))

    # Vector ink: table rules, boxes, drawn Gantt bars. A full-page background
    # fill would swamp the measurement, so ignore anything that covers
    # essentially the whole page.
    page_area = abs(page.rect)
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])
        if abs(rect) > 0.95 * page_area:
            continue
        add(rect)

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


# A non-Times face covering at least this share of the document's characters is
# body text in the wrong font, not a figure label.
FOREIGN_FONT_BODY_SHARE = 0.15


def _font_char_share(spans: Sequence[Span], names: Sequence[str]) -> float:
    """Fraction of all characters set in any of the named fonts.

    Args:
        spans: Every text run in the document.
        names: Font names to measure.

    Returns:
        Share between 0.0 and 1.0; 0.0 when the document has no text.
    """
    wanted = set(names)
    total = sum(len(s.text) for s in spans)
    if not total:
        return 0.0
    return sum(len(s.text) for s in spans if s.font in wanted) / total


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
        # Normalise whitespace first: PDF text extraction breaks a run at the
        # line end, so "[confirm the\nfacility]" would otherwise evade a
        # literal-space pattern entirely.
        text = re.sub(r"\s+", " ", page.get_text())
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


# Sources whose mtime must predate the PDF. Globs are relative to the project
# directory, which is inferred from the PDF path.
SOURCE_GLOBS = ("*.qmd", "sections/*.qmd", "tex/*.tex", "_quarto.yml",
                "references.bib", "*.csl")


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


# --- Word (.docx) checks ---------------------------------------------------
#
# The submitted artefact is the PDF, but the supervisor reads the .docx, and a
# Word file in Calibri 12pt on Letter undermines every conversation about
# layout. These checks hold the .docx to the same rules, measured from OOXML
# rather than eyeballed. Units: twips (1/1440 in) for geometry, half-points for
# type size.

TWIPS_PER_MM = 1440 / 25.4
DOCX_BODY_HALF_PT = 22  # 11 pt


def _docx_part(path: Path, name: str) -> str:
    """Return one XML part of a .docx as text.

    Args:
        path: Path to the .docx.
        name: Zip member name, e.g. ``word/document.xml``.

    Returns:
        The member's text, or "" if it is absent.
    """
    with zipfile.ZipFile(path) as z:
        if name not in z.namelist():
            return ""
        return z.read(name).decode("utf-8", "ignore")


def _attr(xml: str, tag: str, attr: str) -> str | None:
    """Find one attribute of the first occurrence of a tag.

    Attribute order is not stable -- pandoc re-serialises alphabetically -- so
    this searches within the matched tag rather than assuming a fixed order.

    Args:
        xml: XML text to search.
        tag: Tag name without the ``w:`` prefix.
        attr: Attribute name without the ``w:`` prefix.

    Returns:
        The attribute value, or None.
    """
    m = re.search(rf"<w:{tag}\b[^>]*>", xml)
    if not m:
        return None
    a = re.search(rf'w:{attr}="([^"]+)"', m.group(0))
    return a.group(1) if a else None


def check_docx(path: Path) -> list[CheckResult]:
    """Validate a .docx against the same MSCA formatting rules as the PDF.

    Args:
        path: Path to the Word document.

    Returns:
        All check results.
    """
    results = [check_freshness(path)]
    doc = _docx_part(path, "word/document.xml")
    styles = _docx_part(path, "word/styles.xml")

    # Page size
    w, h = _attr(doc, "pgSz", "w"), _attr(doc, "pgSz", "h")
    if w and h:
        wmm, hmm = int(w) / TWIPS_PER_MM, int(h) / TWIPS_PER_MM
        ok = abs(wmm - 210) < 1 and abs(hmm - 297) < 1
        results.append(CheckResult(
            "A4 page size", PASS if ok else FAIL,
            f"{wmm:.0f} x {hmm:.0f} mm" + ("" if ok else " (A4 is 210 x 297)")))
    else:
        results.append(CheckResult(
            "A4 page size", FAIL,
            "no <w:pgSz> -- Word will use its locale default (Letter in the US). "
            "Set a reference-doc: pixi run refdoc"))

    # Margins
    m = re.search(r"<w:pgMar\b[^>]*>", doc)
    if m:
        vals = {k: int(v) / TWIPS_PER_MM
                for k, v in re.findall(r'w:(top|right|bottom|left)="(\d+)"', m.group(0))}
        bad = {k: v for k, v in vals.items() if v < MIN_MARGIN_MM}
        detail = ", ".join(f"{k} {v:.1f}mm" for k, v in sorted(vals.items()))
        results.append(CheckResult(
            "Margins >= 15 mm", FAIL if bad else PASS,
            (f"below 15mm on: {', '.join(sorted(bad))} | " if bad else "") + detail))
    else:
        results.append(CheckResult("Margins >= 15 mm", FAIL, "no <w:pgMar> in the document"))

    # Default font and size, from docDefaults
    dd = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    dd_xml = dd.group(0) if dd else ""
    font = _attr(dd_xml, "rFonts", "ascii")
    results.append(CheckResult(
        "Times fonts", PASS if font and TIMES_RE.search(font) else FAIL,
        f"default font {font!r}" + ("" if font and TIMES_RE.search(font)
                                    else " -- must be a Times family")))

    sizes = [int(v) for v in re.findall(r'<w:sz w:val="(\d+)"', styles)]
    dd_size = re.search(r'<w:sz w:val="(\d+)"', dd_xml)
    under = sorted({v for v in sizes if v < DOCX_BODY_HALF_PT})
    if not dd_size:
        results.append(CheckResult("Font size >= 11 pt", FAIL, "no default size in docDefaults"))
    elif under:
        results.append(CheckResult(
            "Font size >= 11 pt", FAIL,
            f"style(s) below 11pt: {', '.join(f'{v/2:g}pt' for v in under)} "
            f"| default {int(dd_size.group(1))/2:g}pt"))
    else:
        results.append(CheckResult(
            "Font size >= 11 pt", PASS,
            f"default {int(dd_size.group(1))/2:g}pt; no style below 11pt"))

    # Footer
    with zipfile.ZipFile(path) as z:
        footers = [n for n in z.namelist() if re.match(r"word/footer\d*\.xml$", n)]
    text = ""
    for f in footers:
        text += "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", _docx_part(path, f)))
    results.append(CheckResult(
        "Footer 'Part B - Page X of Y'",
        PASS if "Part B - Page" in text else FAIL,
        f"footer text {text.strip()!r}" if footers else
        "no footer part in the document"))

    # Placeholders, over the body text
    body = re.sub(r"\s+", " ", " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc)))
    hits = []
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern == r"\*\*":
            continue  # markdown bold never survives into OOXML
        for match in re.finditer(pattern + r".{0,45}", body, re.IGNORECASE):
            hits.append(repr(match.group(0)[:52]))
    results.append(CheckResult(
        "No unresolved placeholders", FAIL if hits else PASS,
        f"{len(hits)} found -- {' | '.join(hits[:4])}" if hits
        else "none of the placeholder patterns present"))

    return results


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

    if pdf_path.suffix.lower() == ".docx":
        # Same rules, different container. The .docx has no page count until
        # Word lays it out, so --max-pages does not apply to it.
        return check_docx(pdf_path)

    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            # Truncated or interrupted render. Bail before the per-page checks,
            # which index page 0 and would raise IndexError, discarding every
            # result computed so far.
            return [
                CheckResult(
                    "Readable PDF", FAIL,
                    f"{pdf_path} contains 0 pages -- the file is truncated or "
                    "the render was interrupted; re-run `pixi run build`",
                )
            ]
        spans = list(iter_spans(doc))
        return [
            check_freshness(pdf_path),
            check_page_size(doc),
            check_fonts(doc, spans),
            check_font_sizes(spans, doc.page_count),
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
    # the ONLY argument: sniffing for it anywhere in argv meant
    # `... partB1.pdf --max-pages 10 --self-check` exited 0 without ever opening
    # the PDF -- a one-flag bypass of the entire gate.
    if "--self-check" in sys.argv[1:]:
        if sys.argv[1:] != ["--self-check"]:
            raise SystemExit(
                "--self-check runs the internal assertions only and takes no "
                "other arguments.\n"
                "  Did you mean: check_msca_compliance.py <pdf> --part-b1"
            )
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
