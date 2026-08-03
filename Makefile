# =====================================================================
#  Convenience wrapper. Works with Pixi (recommended) or a system
#  install of Quarto + a TeX engine + poppler.
#
#    make setup     one-time TeX install (via Quarto/TinyTeX)
#    make pdf       build Part B-1 and check the 10-page limit
#    make b2        build Part B-2
#    make preview   live preview while writing
#    make check     re-run the page-limit check on the last build
#    make clean     remove build artefacts
#
#  If you use Pixi, you can also just run: pixi run pdf
# =====================================================================

QUARTO ?= quarto
PYTHON ?= python
BUILD  := _build
LIMIT  := 10

.PHONY: setup pdf b2 all preview check clean

setup:
	$(QUARTO) install tinytex --no-prompt --update-path

pdf:
	$(QUARTO) render partB1.qmd
	$(PYTHON) scripts/check_pagecount.py $(BUILD)/partB1.pdf $(LIMIT)

b2:
	$(QUARTO) render partB2.qmd

all:
	$(QUARTO) render
	$(PYTHON) scripts/check_pagecount.py $(BUILD)/partB1.pdf $(LIMIT)

preview:
	sh scripts/preview.sh

check:
	$(PYTHON) scripts/check_pagecount.py $(BUILD)/partB1.pdf $(LIMIT)

clean:
	rm -rf $(BUILD) .quarto
