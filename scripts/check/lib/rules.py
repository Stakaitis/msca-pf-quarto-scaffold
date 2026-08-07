"""The MSCA formatting rules, as values.

Every threshold and pattern the checks compare against lives here, so changing
a rule means editing one file and nothing else. The rules themselves are quoted
in the module docstring of scripts/check/compliance.py.
"""

from __future__ import annotations

import re

PT_PER_MM = 72.0 / 25.4
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
A4_TOLERANCE_PT = 2.0

MIN_MARGIN_MM = 15.0
MIN_BODY_PT = 11.0
MIN_NON_BODY_PT = 8.0

# "Sections 1, 2 and 3 together should not be longer than 10 pages."
# THE single definition of the cap. Callers pass --part-b1 rather than
# repeating the number, so pixi.toml, the Makefile and scripts/check/run.sh cannot
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

# "A minimum of single line spacing" (application form). No single number
# defines it: LaTeX sets 1.20x at 11pt, this project's header 1.24x, Word's
# single for Times New Roman is ~1.15x. 1.10 sits below all of them and well
# above the ~1.0 that deliberate compression produces, so it fails tampering
# without failing a legitimately typeset document. A floor, not a target.
MIN_LINE_SPACING_RATIO = 1.10

# Part A of the portal form caps the proposal summary at 2000 characters.
# Not a Part B rule, but it is the one limit with no warning until submission.
ABSTRACT_MAX_CHARS = 2000

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

FOREIGN_FONT_BODY_SHARE = 0.15

SOURCE_GLOBS = ("*.qmd", "sections/*.qmd", "tex/*.tex", "_quarto.yml",
                "references.bib", "*.csl")

TWIPS_PER_MM = 1440 / 25.4

DOCX_BODY_HALF_PT = 22  # 11 pt
