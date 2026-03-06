#!/bin/sh
# version.sh — Query or preview version bumps without writing.
#
# Usage:
#   ./scripts/version.sh              Show current version
#   ./scripts/version.sh --preview    Show what each bump kind would produce
#   ./scripts/version.sh patch        Show what bumping 'patch' would produce
#   ./scripts/version.sh rc           Show what bumping 'rc' would produce
#
# This script is read-only — it never modifies __about__.py.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ABOUT="src/pytest_verdict/__about__.py"

# Extract current version without importing (works outside hatch env)
CURRENT=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$ABOUT")

KIND="${1:-}"

# ── Show current ─────────────────────────────────────────────────────

if [ -z "$KIND" ]; then
    echo "$CURRENT"
    exit 0
fi

# ── Preview all bumps ────────────────────────────────────────────────

preview_bump() {
    hatch run python -c "
from psclaude._version import Version
v = Version.parse('$CURRENT')
print(getattr(v, 'bump_$1', v.release)())
" 2>/dev/null
}

if [ "$KIND" = "--preview" ]; then
    printf 'current:  %s\n' "$CURRENT"
    printf '\n'
    printf 'patch:    %s\n' "$(preview_bump patch)"
    printf 'minor:    %s\n' "$(preview_bump minor)"
    printf 'major:    %s\n' "$(preview_bump major)"
    printf 'dev:      %s\n' "$(preview_bump dev)"
    printf 'alpha:    %s\n' "$(preview_bump alpha)"
    printf 'beta:     %s\n' "$(preview_bump beta)"
    printf 'rc:       %s\n' "$(preview_bump rc)"
    printf 'release:  %s\n' "$(preview_bump release)"
    exit 0
fi

# ── Preview single bump ─────────────────────────────────────────────

case "$KIND" in
    patch|minor|major|dev|alpha|beta|rc|release)
        NEXT=$(preview_bump "$KIND")
        printf '%s → %s\n' "$CURRENT" "$NEXT"
        ;;
    *)
        printf 'Unknown bump kind: %s\n' "$KIND" >&2
        printf 'Valid: patch, minor, major, dev, alpha, beta, rc, release\n' >&2
        exit 1
        ;;
esac
