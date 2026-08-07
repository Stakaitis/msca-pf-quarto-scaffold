"""Prove each check fails the document it exists to catch.

WHY THIS EXISTS: a broken check does not raise -- it returns PASS. The gate is
the only thing standing between a malformed PDF and a submission, so "the gate
ran and said nothing" and "the gate is dead" look identical from the outside.
These tests make them look different.

Each test builds a PDF that violates exactly one rule and asserts that rule
fails, plus a compliant control asserting it passes. Fixtures are synthesised
with PyMuPDF rather than rendered through Quarto: no LaTeX, no network, runs in
under a second, and a fixture can be malformed in ways Quarto would refuse to
produce.

    python scripts/check/tests/test_checks.py     # no pytest needed
    pytest scripts/check/tests/                   # also works if you have it

NOT COVERED HERE: font-family rejection needs a real embedded Latin Modern face,
which PyMuPDF cannot synthesise. That classifier is asserted instead by
`python scripts/check/compliance.py --self-check`, which both this file and the
build run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib._pymupdf import fitz  # noqa: E402
from lib.checks import run_checks  # noqa: E402
from lib.model import FAIL, PASS  # noqa: E402
from lib.rules import PT_PER_MM  # noqa: E402

A4 = (595.276, 841.890)          # points, the size _quarto.yml asks geometry for
LETTER = (612.0, 792.0)          # what a bypassed template silently produces
BODY_PT = 11.0
MARGIN_PT = 16 * PT_PER_MM       # the geometry setting, comfortably over the 15 mm rule


def _write(tmp: Path, name: str, *, pages: int = 1, size=A4,
           margin: float = MARGIN_PT, footer: bool = True,
           body: str = "Neutrophils respond to Candida within minutes.",
           body_pt: float = BODY_PT) -> Path:
    """Build a minimal PDF. Every argument is a rule this file bends on purpose."""
    doc = fitz.open()
    for n in range(1, pages + 1):
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((margin, margin + body_pt), body,
                         fontname="tiro", fontsize=body_pt)   # tiro = Times-Roman
        if footer:
            page.insert_text((margin, size[1] - margin),
                             f"Part B - Page {n} of {pages}",
                             fontname="tiro", fontsize=9)
    out = tmp / name
    doc.save(out)
    doc.close()
    return out


def _result(pdf: Path, name_fragment: str, max_pages=None):
    """The single CheckResult whose name contains `name_fragment`."""
    hits = [r for r in run_checks(pdf, max_pages) if name_fragment.lower() in r.name.lower()]
    assert len(hits) == 1, f"expected one check matching {name_fragment!r}, got {[h.name for h in hits]}"
    return hits[0]


# --------------------------------------------------------------------------
# the control: a document that breaks nothing must pass everything
# --------------------------------------------------------------------------

def test_compliant_pdf_passes_every_hard_check(tmp):
    # PyMuPDF writes "tiro" as base-14 Times-Roman, which is a Times family but is
    # NOT embedded -- and the gate rightly rejects that, so the font check cannot
    # pass on a synthesised fixture. Asserting a subset rather than skipping the
    # check keeps the test honest: if any OTHER check starts failing a clean
    # document, this fails.
    pdf = _write(tmp, "good.pdf", pages=2)
    failures = {r.name for r in run_checks(pdf, max_pages=10)
                if r.hard and r.status == FAIL}
    assert failures <= {"Times fonts, embedded"}, f"clean document failed: {failures}"


# --------------------------------------------------------------------------
# one test per silent-failure mode
# --------------------------------------------------------------------------

def test_us_letter_fails_page_size(tmp):
    # The 2026-07-28 regression: a bypassed template renders Letter, and nothing
    # about the PDF looks wrong until an evaluator opens it.
    assert _result(_write(tmp, "letter.pdf", size=LETTER), "page size").status == FAIL
    assert _result(_write(tmp, "a4.pdf"), "page size").status == PASS


def test_narrow_margin_fails(tmp):
    # 8 mm: inside the 15 mm rule, but not so far inside that it looks obviously wrong.
    tight = _write(tmp, "tight.pdf", margin=8 * PT_PER_MM)
    assert _result(tight, "margin").status == FAIL
    assert _result(_write(tmp, "wide.pdf"), "margin").status == PASS


def test_missing_footer_fails(tmp):
    assert _result(_write(tmp, "nofooter.pdf", footer=False), "footer").status == FAIL
    assert _result(_write(tmp, "footer.pdf"), "footer").status == PASS


def test_page_limit_is_enforced_only_when_given(tmp):
    over = _write(tmp, "over.pdf", pages=11)
    assert _result(over, "page limit", max_pages=10).status == FAIL
    # max_pages=None is how Part B-2 and the Word files are checked
    assert not [r for r in run_checks(over, None) if "page limit" in r.name.lower()
                and r.status == FAIL]


def test_body_text_below_11pt_fails(tmp):
    small = _write(tmp, "small.pdf", body_pt=9.5)
    assert _result(small, "font size").status == FAIL
    assert _result(_write(tmp, "ok.pdf"), "font size").status == PASS


def test_placeholder_left_in_text_fails(tmp):
    left = _write(tmp, "placeholder.pdf", body="We will [verb] the [what, in WP1].")
    assert _result(left, "placeholder").status == FAIL
    assert _result(_write(tmp, "clean.pdf"), "placeholder").status == PASS


def test_footer_total_must_match_reality(tmp):
    # A footer saying "of 9" on a 10-page document: the count is wrong, not absent.
    doc = fitz.open()
    for n in range(1, 4):
        page = doc.new_page(width=A4[0], height=A4[1])
        page.insert_text((MARGIN_PT, MARGIN_PT + BODY_PT), "Body text here.",
                         fontname="tiro", fontsize=BODY_PT)
        page.insert_text((MARGIN_PT, A4[1] - MARGIN_PT), f"Part B - Page {n} of 9",
                         fontname="tiro", fontsize=9)
    out = tmp / "wrongtotal.pdf"
    doc.save(out); doc.close()
    assert _result(out, "footer").status == FAIL


# --------------------------------------------------------------------------
# runner -- works under pytest, and standalone so no dependency is required
# --------------------------------------------------------------------------

def _main() -> int:
    import tempfile
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as d:
            try:
                fn(Path(d))
                print(f"  PASS  {name}")
            except Exception:
                failed += 1
                print(f"  FAIL  {name}")
                traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
