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

CHECK="${PYTHON:-python} scripts/check_msca_compliance.py"
status=0

# Part B-1 is the only document with a page limit: 10 pages, hard.
$CHECK _build/partB1.pdf --max-pages 10 || status=1
$CHECK _build/partB2.pdf --no-page-limit || status=1
# Supervisor-review extract. Not submitted, but it is rendered from the same
# sections, and it is the file that regressed on 2026-07-28 — so it is checked.
# Any other PDF the project renders (e.g. a supervisor-review extract) is checked
# too, minus the page cap. Keeps this script working in any project layout.
for extra in _build/*.pdf; do
    case "$extra" in
        _build/partB1.pdf|_build/partB2.pdf|"_build/*.pdf") continue ;;
    esac
    $CHECK "$extra" --no-page-limit || status=1
done

if [ "$status" -ne 0 ]; then
    echo "BUILD FAILED: at least one PDF is not MSCA-compliant (see above)."
    echo "Nothing here may be submitted until every hard check passes."
fi
exit "$status"
