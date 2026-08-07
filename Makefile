# =====================================================================
#  Convenience wrapper. Works with Pixi (recommended) or a system
#  install of Quarto + a TeX engine + PyMuPDF.
#
#    make setup     one-time TeX install (via Quarto/TinyTeX)
#    make build     THE ENTRY POINT — render every part, validate every PDF
#    make pdf       build Part B-1 only, and validate it
#    make b2        build Part B-2 only, and validate it
#    make preview   live preview while writing
#    make check     re-validate the last build without re-rendering
#    make test      prove the gate still catches what it should
#    make hooks     install the pre-commit compliance hook
#    make clean     remove build artefacts
#
#  `make build` (or `pixi run build`) is the ONLY sanctioned build. A bare
#  `quarto render` produces a PDF nobody has checked, which is exactly how a
#  US Letter / Latin Modern / footer-less render reached _build on 2026-07-28.
#
#  If you use Pixi, you can also just run: pixi run build
# =====================================================================

QUARTO ?= quarto
PYTHON ?= python
BUILD  := _build
CHECK  := $(PYTHON) scripts/check/compliance.py

.PHONY: setup build pdf b2 all preview check test hooks clean

setup:
	$(QUARTO) install tinytex --no-prompt --update-path

build:
	sh scripts/build/render.sh
	PYTHON="$(PYTHON)" sh scripts/check/run.sh

pdf:
	$(QUARTO) render partB1.qmd
	$(CHECK) $(BUILD)/partB1.pdf --part-b1

b2:
	$(QUARTO) render partB2.qmd
	$(CHECK) $(BUILD)/partB2.pdf --no-page-limit

all: build

preview:
	sh scripts/build/preview.sh

check:
	PYTHON="$(PYTHON)" sh scripts/check/run.sh

test:
	$(PYTHON) scripts/check/tests/test_checks.py
	$(CHECK) --self-check

hooks:
	sh scripts/hooks/install.sh

clean:
	rm -rf $(BUILD) .quarto *_files *.tex *.pdf
