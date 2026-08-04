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
CHECK  := $(PYTHON) scripts/check_msca_compliance.py

.PHONY: setup build pdf b2 all preview check hooks clean

setup:
	$(QUARTO) install tinytex --no-prompt --update-path

build:
	$(QUARTO) render
	PYTHON="$(PYTHON)" sh scripts/check_all.sh

pdf:
	$(QUARTO) render partB1.qmd
	$(CHECK) $(BUILD)/partB1.pdf --part-b1

b2:
	$(QUARTO) render partB2.qmd
	$(CHECK) $(BUILD)/partB2.pdf --no-page-limit

all: build

preview:
	sh scripts/preview.sh

check:
	PYTHON="$(PYTHON)" sh scripts/check_all.sh

hooks:
	sh scripts/install_hooks.sh

clean:
	rm -rf $(BUILD) .quarto
