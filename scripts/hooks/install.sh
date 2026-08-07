#!/bin/sh
# Install the pre-commit hook that refuses to commit a non-compliant Part B PDF.
# Run once per clone:  pixi run hooks   (or: make hooks)
set -eu

# `git rev-parse --git-path` resolves correctly in a plain clone, a linked
# worktree, a submodule, and under a custom core.hooksPath. Hardcoding
# "$(git rev-parse --show-toplevel)/.git/hooks" is wrong in the last three.
hook=$(git rev-parse --git-path hooks/pre-commit)
mkdir -p "$(dirname "$hook")"

# Never clobber someone else's hook without a copy.
if [ -e "$hook" ] && ! grep -q 'check/compliance' "$hook" 2>/dev/null; then
    cp "$hook" "$hook.bak"
    echo "existing pre-commit hook backed up to $hook.bak"
fi

cat > "$hook" <<'HOOK'
#!/bin/sh
# MSCA formatting gate. Blocks a commit that would record a PDF failing the
# formatting rules. Bypass only with a reason you can defend: git commit -n
set -eu

# Locate the checker wherever the Quarto project sits, so this works whether it
# is at the repo root or in a subdirectory such as work/.
checker=$(git ls-files --full-name | grep -m1 'scripts/check/compliance\.py$' || true)

# -z with a null-delimited read: staged paths can contain spaces, and git
# C-quotes non-ASCII names unless told otherwise. Word-splitting a filename with
# a space turned it into two nonexistent paths and blocked the commit with an
# opaque FileNotFoundError.
staged=$(git -c core.quotePath=false diff --cached -z --name-only --diff-filter=d \
         | tr '\0' '\n' | grep -E '_build/.*\.pdf$' || true)

[ -n "$staged" ] || exit 0

if [ -z "$checker" ] || [ ! -f "$checker" ]; then
    # Do NOT silently pass: PDFs are staged and cannot be verified. The old
    # `[ -f "$checker" ] || exit 0` disabled the whole gate the moment the path
    # changed, and said nothing.
    echo "pre-commit: PDFs are staged but the compliance checker was not found." >&2
    echo "  Expected scripts/check/compliance.py somewhere in this repo." >&2
    echo "  Fix that, or bypass deliberately with 'git commit -n'." >&2
    exit 1
fi

project_dir=$(dirname "$(dirname "$checker")")
root=$(git rev-parse --show-toplevel)

status=0
while IFS= read -r pdf; do
    [ -n "$pdf" ] || continue
    case "$pdf" in
        */partB1.pdf) limit="--part-b1" ;;
        *)            limit="--no-page-limit" ;;
    esac
    echo "pre-commit: checking $pdf"
    ( cd "$root/$project_dir" && python3 scripts/check/compliance.py \
        "$root/$pdf" "$limit" ) || status=1
done <<STAGED
$staged
STAGED

if [ "$status" -ne 0 ]; then
    echo "" >&2
    echo "pre-commit: a staged PDF fails the MSCA formatting rules (above)." >&2
    echo "Fix it with 'pixi run build', or bypass with 'git commit -n'." >&2
fi
exit "$status"
HOOK

chmod +x "$hook"
echo "Installed $hook"
