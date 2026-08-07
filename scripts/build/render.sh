#!/bin/sh
# Render every part of the proposal, reliably.
#
# WHY THIS EXISTS: `quarto render` in PROJECT mode fails intermittently here:
#
#   ERROR: NotFound: No such file or directory (os error 2):
#          rename '.../partB2.pdf' -> '.../_build/partB2.pdf'
#   ERROR: NotFound: No such file or directory (os error 2): tmpfile
#
# and variants naming `<doc>_files` or `<doc>_files/mediabag`. Quarto writes each
# output into the source directory and then moves it into `output-dir`; in
# project mode that move races against the next document's render.
#
# Clearing `.quarto` first was NOT enough -- the failure still recurred. What is
# reliable, observed over many runs, is rendering each file INDIVIDUALLY: a
# single-file render still picks up `_quarto.yml` (so it keeps the A4/Times/
# footer format block and still writes into `_build/`), it just does not enter
# the project-level move logic where the race lives.
#
# So: one `quarto render <file>` per document, and verify every expected output
# actually appeared. A missing output is a hard failure here rather than a
# stale PDF left quietly in place -- which is the failure mode that nearly had
# numbers reported from a render that never happened.
#
# Usage:  pixi run build   (calls this, then scripts/check/run.sh)

set -eu

cd "$(dirname "$0")/.." || exit 2

# Quarto's project cache: regenerated on every render, only ever a liability.
rm -rf .quarto

# Leftovers from earlier renders sit in the source directory and confuse the
# move step. They are all regenerable.
rm -rf ./*_files
rm -f ./*.tex ./*.pdf

# The documents to render, taken from `project: render:` in _quarto.yml so this
# list cannot drift from the one the compliance gate assumes.
docs=$(sed -n '/^  render:/,/^[a-z]/p' _quarto.yml \
       | sed -n 's/^ *- *//p' | grep '\.qmd$' || true)

if [ -z "$docs" ]; then
    echo "render.sh: no documents found under 'project: render:' in _quarto.yml" >&2
    exit 2
fi

# Every scored sub-section is its own file, so a missing or emptied one is a
# missing evaluator answer. Checking here means you find out at build time
# rather than when a reviewer scores the gap.
#
# The list is the nine sub-sections the handbook and the evaluator manual
# score. Add a file here when the call adds a sub-section, and only then.
required="_1.1_objectives _1.2_methodology _1.3_supervision _1.4_researcher
          _2.1_career _2.2_dissemination _2.3_magnitude
          _3.1_workplan _3.2_host"
missing=""
for req in $required; do
    f="sections/${req}.qmd"
    if [ ! -f "$f" ]; then
        missing="$missing\n  $f is MISSING"
    elif [ "$(grep -cvE '^\s*(<!--.*-->)?\s*$' "$f" 2>/dev/null)" -lt 3 ]; then
        missing="$missing\n  $f is effectively empty"
    fi
done
if [ -n "$missing" ]; then
    printf 'render.sh: scored sub-section(s) missing or empty:%b\n' "$missing" >&2
    echo "  Each is a question an evaluator scores. Restore it, or if the call" >&2
    echo "  genuinely dropped it, remove it from 'required' in this script." >&2
    exit 1
fi

status=0
for doc in $docs; do
    [ -f "$doc" ] || { echo "render.sh: $doc is listed but missing" >&2; status=1; continue; }
    printf '\n=== rendering %s ===\n' "$doc"
    if ! quarto render "$doc"; then
        echo "render.sh: FAILED to render $doc" >&2
        status=1
    fi
done

# Every listed document must have produced a PDF. Checking this here means a
# failed render is caught now, not implied later by a suspiciously old file.
for doc in $docs; do
    out="_build/$(basename "$doc" .qmd).pdf"
    if [ ! -f "$out" ]; then
        echo "render.sh: expected $out was not produced" >&2
        status=1
    fi
done

# A PDF left in the source directory means the move step failed.
leftover=$(ls ./*.pdf 2>/dev/null || true)
if [ -n "$leftover" ]; then
    echo "render.sh: PDFs left in the source directory: $leftover" >&2
    status=1
fi

exit "$status"
