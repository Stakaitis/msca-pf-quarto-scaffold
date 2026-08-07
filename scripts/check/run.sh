#!/bin/sh
# Validate every rendered Part B PDF against the MSCA formatting rules.
#
# Single source of truth for "which PDFs exist and what limit each one has" —
# pixi.toml, the Makefile and the Dockerfile all call this rather than each
# repeating the list. Adding a new part? Add one line here, nowhere else.
#
# Runs every document even when an earlier one fails, so one build shows you
# every problem instead of one per re-run. Exits non-zero if any hard check
# failed anywhere.
set -u

# Run from the project root whichever directory the caller was in, so a
# relative `scripts/...` path and `_build/*.pdf` always resolve. Without this a
# run from elsewhere reported "cannot read _build/partB1.pdf", which reads as a
# compliance failure rather than a wrong working directory.
# Run from the project root, wherever this script sits under scripts/. Walk up
# looking for _quarto.yml rather than counting "../..", so moving this file
# between subdirectories cannot silently aim the build at the wrong directory.
root=$(cd "$(dirname "$0")" && while [ ! -f _quarto.yml ] && [ "$PWD" != / ]; do cd ..; done; pwd)
[ -f "$root/_quarto.yml" ] || { echo "$(basename "$0"): no _quarto.yml above $0" >&2; exit 2; }
cd "$root" || exit 2

[ -f scripts/check/compliance.py ] || {
    echo "run.sh: scripts/check/compliance.py not found" >&2
    exit 2
}

CHECK="${PYTHON:-python} scripts/check/compliance.py"
status=0

# Part B-1 is the only document with a page limit: 10 pages, hard.
$CHECK _build/partB1.pdf --part-b1 || status=1
$CHECK _build/partB2.pdf --no-page-limit || status=1
# Supervisor-review extract. Not submitted, but it is rendered from the same
# sections, and it is the file that regressed on 2026-07-28 — so it is checked.
# Any other PDF the project renders (e.g. a supervisor-review extract) is checked
# too, minus the page cap. Keeps this script working in any project layout.
# The Part A summary. Not part of Part B at all -- it is pasted into the portal
# form -- but it is the one limit with no warning until submission, so it is
# rendered and checked here like everything else.
if [ -f _build/abstract.pdf ]; then
    $CHECK _build/abstract.pdf --no-page-limit --summary || status=1
fi

for extra in _build/*.pdf; do
    case "$extra" in
        _build/partB1.pdf|_build/partB2.pdf|_build/abstract.pdf|"_build/*.pdf") continue ;;
    esac
    $CHECK "$extra" --no-page-limit || status=1
done

# Word output is held to the same rules. It is not the submitted artefact, but
# the supervisor reads it, and a .docx in Calibri 12pt on Letter undermines
# every conversation about layout. No page cap: Word paginates differently from
# TeX, so its page count is indicative only -- the PDF is the authority.
for docx in _build/*.docx; do
    [ -e "$docx" ] || continue
    $CHECK "$docx" --no-page-limit || status=1
done

if [ "$status" -ne 0 ]; then
    echo "BUILD FAILED: at least one PDF is not MSCA-compliant (see above)."
    echo "Nothing here may be submitted until every hard check passes."
fi
exit "$status"
