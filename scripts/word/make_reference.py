#!/usr/bin/env python3
"""Generate the Word reference document that makes .docx output MSCA-compliant.

Quarto's default .docx has no page size, no margins, Calibri/Consolas at 12 pt
and no footer -- none of which satisfies the MSCA formatting rules. A
``reference-doc`` supplies those defaults to pandoc, so the Word file matches
the PDF: A4, 16 mm margins, Times New Roman 11 pt, and a
``Part B - Page X of Y`` footer at 9 pt.

This is a generator rather than a committed binary so the styling is reviewable
as text and regenerable when pandoc's template changes.

    python scripts/word/make_reference.py            # writes tex/msca-reference.docx
    python scripts/word/make_reference.py --check    # verify the existing file

WHAT IT CANNOT DO: make Word paginate identically to LaTeX. Word and TeX break
lines and justify differently, so the same text at the same size in the same
column will not land on the same pages. The Word file matches on *style*, and
its page count is indicative only -- the PDF remains the authority for the
10-page limit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# --- MSCA values, in the units OOXML uses -----------------------------------

TWIPS_PER_MM = 1440 / 25.4
A4_W_TWIPS = round(210 * TWIPS_PER_MM)   # 11906
A4_H_TWIPS = round(297 * TWIPS_PER_MM)   # 16838
MARGIN_TWIPS = round(16 * TWIPS_PER_MM)  # 907 -- 16 mm, matching _quarto.yml
FOOTER_TWIPS = round(9 * TWIPS_PER_MM)   # 510 -- matches footskip in the LaTeX header

BODY_FONT = "Times New Roman"
BODY_HALF_PT = 22  # w:sz is in half-points, so 22 = 11 pt
FOOTER_HALF_PT = 18  # 9 pt, the same as the PDF footer and above the 8 pt floor

FOOTER_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="center"/>
      <w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}"/><w:sz w:val="{FOOTER_HALF_PT}"/></w:rPr>
    </w:pPr>
    <w:r><w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}"/><w:sz w:val="{FOOTER_HALF_PT}"/></w:rPr>
      <w:t xml:space="preserve">Part B - Page </w:t></w:r>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}"/><w:sz w:val="{FOOTER_HALF_PT}"/></w:rPr><w:t>1</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
    <w:r><w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}"/><w:sz w:val="{FOOTER_HALF_PT}"/></w:rPr>
      <w:t xml:space="preserve"> of </w:t></w:r>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}"/><w:sz w:val="{FOOTER_HALF_PT}"/></w:rPr><w:t>1</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>
"""

SECT_PR = (
    f'<w:sectPr>'
    f'<w:footerReference w:type="default" r:id="rIdMscaFooter"/>'
    f'<w:pgSz w:w="{A4_W_TWIPS}" w:h="{A4_H_TWIPS}"/>'
    f'<w:pgMar w:top="{MARGIN_TWIPS}" w:right="{MARGIN_TWIPS}" '
    f'w:bottom="{MARGIN_TWIPS}" w:left="{MARGIN_TWIPS}" '
    f'w:header="{FOOTER_TWIPS}" w:footer="{FOOTER_TWIPS}" w:gutter="0"/>'
    f'</w:sectPr>'
)


def default_reference_docx(dest: Path) -> Path:
    """Write pandoc's built-in reference.docx to ``dest``.

    Args:
        dest: Where to write the extracted template.

    Returns:
        The path written.

    Raises:
        RuntimeError: If pandoc/quarto cannot supply the data file.
    """
    for cmd in (
        ["quarto", "pandoc", "--print-default-data-file", "reference.docx"],
        ["pandoc", "--print-default-data-file", "reference.docx"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        if out[:2] == b"PK":
            dest.write_bytes(out)
            return dest
    raise RuntimeError(
        "Could not obtain pandoc's default reference.docx. Is quarto on PATH?"
    )


def patch_styles(xml: str) -> str:
    """Force Times New Roman at 11 pt as the document-wide default.

    Args:
        xml: Contents of ``word/styles.xml``.

    Returns:
        The patched XML.
    """
    # Every rFonts declaration, including docDefaults and each named style.
    xml = re.sub(
        r'<w:rFonts[^/]*?/>',
        f'<w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" '
        f'w:eastAsia="{BODY_FONT}" w:cs="{BODY_FONT}"/>',
        xml,
    )
    # Body size. Two separate jobs:
    #   1. docDefaults is the document-wide default and MUST be exactly 11 pt.
    #      pandoc ships 24 half-points (12 pt) there.
    #   2. No named style may sit below 11 pt, or body-ish text inherits an
    #      under-size. Headings declare larger sizes and are left alone --
    #      "text elements other than the body text ... may deviate".
    def _raise_to_body(match: "re.Match[str]") -> str:
        tag, value = match.group(1), int(match.group(2))
        return f'<w:{tag} w:val="{max(value, BODY_HALF_PT)}"/>'

    xml = re.sub(r'<w:(sz|szCs) w:val="(\d+)"\s*/>', _raise_to_body, xml)

    # Now force docDefaults itself to exactly 11 pt (the sweep above only
    # guarantees "not below").
    def _fix_defaults(match: "re.Match[str]") -> str:
        block = match.group(0)
        block = re.sub(r'<w:sz w:val="\d+"\s*/>', f'<w:sz w:val="{BODY_HALF_PT}"/>', block)
        block = re.sub(r'<w:szCs w:val="\d+"\s*/>', f'<w:szCs w:val="{BODY_HALF_PT}"/>', block)
        return block

    xml = re.sub(r'<w:docDefaults>.*?</w:docDefaults>', _fix_defaults, xml, flags=re.S)
    return xml


def build(dest: Path) -> Path:
    """Build the MSCA reference .docx.

    Args:
        dest: Output path for the reference document.

    Returns:
        The path written.
    """
    scratch = dest.parent / ".ref_default.docx"
    default_reference_docx(scratch)

    with zipfile.ZipFile(scratch) as src:
        names = src.namelist()
        blobs = {n: src.read(n) for n in names}
    scratch.unlink()

    styles = blobs["word/styles.xml"].decode("utf-8")
    blobs["word/styles.xml"] = patch_styles(styles).encode("utf-8")

    doc = blobs["word/document.xml"].decode("utf-8")
    doc = re.sub(r"<w:sectPr>.*?</w:sectPr>", SECT_PR, doc, flags=re.S)
    if "<w:sectPr>" not in doc:
        doc = doc.replace("</w:body>", SECT_PR + "</w:body>")
    blobs["word/document.xml"] = doc.encode("utf-8")

    blobs["word/footer1.xml"] = FOOTER_XML.encode("utf-8")

    rels = blobs["word/_rels/document.xml.rels"].decode("utf-8")
    if "rIdMscaFooter" not in rels:
        rels = rels.replace(
            "</Relationships>",
            '<Relationship Id="rIdMscaFooter" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/footer" Target="footer1.xml"/></Relationships>',
        )
    blobs["word/_rels/document.xml.rels"] = rels.encode("utf-8")

    ct = blobs["[Content_Types].xml"].decode("utf-8")
    if "footer1.xml" not in ct:
        ct = ct.replace(
            "</Types>",
            '<Override PartName="/word/footer1.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            "</Types>",
        )
    blobs["[Content_Types].xml"] = ct.encode("utf-8")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for name in names + ["word/footer1.xml"]:
            out.writestr(name, blobs[name])
    return dest


def main(argv: list[str]) -> int:
    """Build or verify the reference document.

    Args:
        argv: Command-line arguments excluding the program name.

    Returns:
        Process exit code.
    """
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("tex/msca-reference.docx"))
    args = ap.parse_args(argv)
    path = build(args.out)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(f"  A4 {A4_W_TWIPS}x{A4_H_TWIPS} twips, {MARGIN_TWIPS} twips margins "
          f"(16 mm), {BODY_FONT} {BODY_HALF_PT / 2:g} pt, footer at "
          f"{FOOTER_HALF_PT / 2:g} pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
