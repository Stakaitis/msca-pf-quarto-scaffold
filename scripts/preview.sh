#!/bin/sh
# Live hot-reloading preview for the writing loop.
#
# Two Quarto behaviours this works around (both verified 2026-08-03, Quarto
# 1.9.38, TinyTeX/TeX Live 2026 on this machine):
#
#   1. `quarto preview` watches only the file named on the command line. Files
#      pulled in with {{< include >}} are NOT watched, so editing
#      sections/_excellence.qmd leaves the preview silently stale. The poller
#      below nudges the master's mtime, which the watcher does notice.
#
#   2. `quarto preview` to PDF renders once and then FAILS on every re-render
#      ("updating tlmgr" -> "compilation failed"). HTML re-renders are clean and
#      ~3x faster, so the live loop runs on HTML.
#
# HTML shows you prose and flow, NOT pagination. The 10-page limit is the hard
# constraint on Part B-1, so check it with `pixi run pdf` (renders the real PDF
# and prints the page count) before you call any section done.
#
# Usage:  pixi run preview   |   make preview   |   sh scripts/preview.sh
# Ctrl-C stops both the preview and the poller.

cd "$(dirname "$0")/.." || exit 1
TARGET=${1:-partB1.qmd}

# ponytail: polling loop rather than an fswatch/entr dependency — a 2 s lag is
# unnoticeable next to a ~4 s render. Swap in `fswatch -o sections/` if you ever
# want it instant.
# Compare against a stamp file this script owns, NOT against $TARGET. Comparing
# to $TARGET meant one section file with a future mtime (a bad clock, a restored
# backup, a copy off a FAT drive) kept the condition true forever, rewriting the
# master every 2 s and re-rendering continuously until you noticed the fan.
STAMP=$(mktemp -t msca-preview) || exit 1
while :; do
    if [ -n "$(find sections -name '*.qmd' -newer "$STAMP" 2>/dev/null)" ]; then
        touch "$STAMP" "$TARGET"
    fi
    sleep 2
done &
POLLER=$!
trap 'kill $POLLER 2>/dev/null; rm -f "$STAMP"' EXIT INT TERM

# Fixed port so the URL never changes: http://localhost:4200
# That means you can park it in VS Code's Simple Browser once and just leave it.
quarto preview "$TARGET" --to html --port 4200
