#!/bin/sh
# Install a pre-commit hook that runs the MSCA compliance gate on any staged PDF.
#
# WHY: the gate only helps if it cannot be skipped. `pixi run build` checks the
# PDFs it renders, but nothing stops someone committing a stale non-compliant PDF
# rendered some other way. This closes that gap.
#
# Usage:  pixi run hooks   (or)  sh scripts/install_hooks.sh
#
# ponytail: the hook resolves the project directory at run time rather than
# baking in a path, so this works whether the Quarto project sits at the repo
# root (this scaffold) or in a subdirectory (as it does in the proposal repo).

set -eu
repo_root=$(git rev-parse --show-toplevel)
hook="$repo_root/.git/hooks/pre-commit"

cat > "$hook" <<'HOOK'
#!/bin/sh
set -eu

# Find the checker wherever the Quarto project lives in this repo.
checker=$(git ls-files --full-name | grep -m1 'scripts/check_msca_compliance\.py$' || true)
[ -n "$checker" ] && [ -f "$checker" ] || exit 0
project_dir=$(dirname "$(dirname "$checker")")

status=0
for pdf in $(git diff --cached --name-only --diff-filter=d | grep -E '_build/.*\.pdf$' || true); do
    [ -f "$pdf" ] || continue
    case "$pdf" in
        */partB1.pdf) limit="--max-pages 10" ;;
        *)            limit="--no-page-limit" ;;
    esac
    echo "pre-commit: checking $pdf"
    # shellcheck disable=SC2086
    ( cd "$project_dir" && python scripts/check_msca_compliance.py \
        "${OLDPWD}/$pdf" $limit ) || status=1
done

if [ "$status" -ne 0 ]; then
    echo
    echo "pre-commit REJECTED: a staged PDF is not MSCA-compliant."
    echo "Fix it, or commit with --no-verify if you know exactly why."
fi
exit "$status"
HOOK

chmod +x "$hook"
echo "installed pre-commit hook: $hook"
