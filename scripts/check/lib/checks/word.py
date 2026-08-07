"""The same rules, measured on a .docx instead of a PDF."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..model import FAIL, PASS, CheckResult
from ..rules import (DOCX_BODY_HALF_PT, MIN_MARGIN_MM, PLACEHOLDER_PATTERNS,
                      TIMES_RE, TWIPS_PER_MM)
from .freshness import check_freshness

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
