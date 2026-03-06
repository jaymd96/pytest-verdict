#!/bin/sh
# release.sh — Full release pipeline: bump → check → commit → push → gh release.
#
# Usage:
#   ./scripts/release.sh patch      Bump patch and release (0.2.1 → 0.2.2)
#   ./scripts/release.sh minor      Bump minor and release (0.2.1 → 0.3.0)
#   ./scripts/release.sh major      Bump major and release (0.2.1 → 1.0.0)
#   ./scripts/release.sh rc         Bump to release candidate (0.2.1 → 0.2.2rc1)
#   ./scripts/release.sh dev        Bump to dev version (0.2.1 → 0.2.2.dev1)
#   ./scripts/release.sh alpha      Bump to alpha (0.2.1 → 0.2.2a1)
#   ./scripts/release.sh beta       Bump to beta (0.2.1 → 0.2.2b1)
#   ./scripts/release.sh release    Finalize pre-release (0.2.2rc1 → 0.2.2)
#
#   ./scripts/release.sh --dry-run patch   Preview without executing
#
# Requirements: git, gh (GitHub CLI), hatch
#
# What happens:
#   1. Validates clean working tree on main, pulls latest
#   2. Bumps version in __about__.py
#   3. Runs full quality gate (lint + tests)
#   4. Commits, pushes, creates GitHub release
#   5. GitHub Actions publish workflow handles PyPI upload
#
# Pre-releases (dev/alpha/beta/rc) are tagged as GitHub pre-releases
# and will NOT be installed by default with `pip install jaymd96-pytest-verdict`.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Helpers ──────────────────────────────────────────────────────────

info() { printf '==> %s\n' "$1"; }
ok()   { printf '  ✓ %s\n' "$1"; }
warn() { printf '  ⚠ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1" >&2; exit 1; }

# ── Arguments ────────────────────────────────────────────────────────

DRY_RUN=false
BUMP=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        -*)        fail "Unknown flag: $arg" ;;
        *)         BUMP="$arg" ;;
    esac
done

[ -n "$BUMP" ] || fail "Usage: $0 [--dry-run] <patch|minor|major|dev|alpha|beta|rc|release>"

case "$BUMP" in
    patch|minor|major|dev|alpha|beta|rc|release) ;;
    *) fail "Invalid bump kind: $BUMP" ;;
esac

# ── Dry-run preview ──────────────────────────────────────────────────

CURRENT=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' src/pytest_verdict/__about__.py)

NEXT=$(hatch run python -c "
from psclaude._version import Version
v = Version.parse('$CURRENT')
if '$BUMP' == 'release':
    print(v.release())
else:
    print(getattr(v, 'bump_$BUMP')())
")

if $DRY_RUN; then
    printf 'Dry run: %s → %s\n' "$CURRENT" "$NEXT"
    printf 'Tag:     v%s\n' "$NEXT"
    case "$BUMP" in
        dev|alpha|beta|rc) printf 'Type:    pre-release\n' ;;
        *)                 printf 'Type:    release\n' ;;
    esac
    exit 0
fi

info "Releasing: $CURRENT → $NEXT"

# ── Guard rails ──────────────────────────────────────────────────────

info "Checking prerequisites"

command -v git >/dev/null 2>&1 || fail "git not found"
command -v gh >/dev/null 2>&1  || fail "gh (GitHub CLI) not found"
command -v hatch >/dev/null 2>&1 || fail "hatch not found"

BRANCH=$(git branch --show-current)
[ "$BRANCH" = "main" ] || fail "Must be on main branch (currently on $BRANCH)"

git diff --quiet && git diff --cached --quiet || fail "Working tree is dirty — commit or stash first"

ok "Clean working tree on main"

info "Pulling latest from origin"
git pull --ff-only origin main
ok "Up to date"

# Check the tag doesn't already exist
if git tag -l "v$NEXT" | grep -q .; then
    fail "Tag v$NEXT already exists. Delete it first or choose a different bump."
fi

ok "Tag v$NEXT is available"

# ── Bump version ─────────────────────────────────────────────────────

info "Bumping version"
hatch run python -c "
from psclaude._version import bump
from pathlib import Path
bump('$BUMP', Path('src/pytest_verdict/__about__.py'))
"
ok "Version: $NEXT"

# ── Quality gate ─────────────────────────────────────────────────────

info "Running lint"
hatch run lint:check
ok "Lint passed"

info "Running tests"
hatch run test
ok "Tests passed"

# ── Commit and push ──────────────────────────────────────────────────

info "Committing"

git add src/pytest_verdict/__about__.py

if git diff --cached --quiet; then
    warn "No changes to commit (version was already $NEXT?)"
else
    git commit -m "Release v$NEXT"
    ok "Committed"
fi

info "Pushing to origin"
git push origin main
ok "Pushed"

# ── Create GitHub release ────────────────────────────────────────────

info "Creating GitHub release"

GH_FLAGS=""
case "$BUMP" in
    dev|alpha|beta|rc) GH_FLAGS="--prerelease" ;;
esac

gh release create "v$NEXT" $GH_FLAGS \
    --title "v$NEXT" \
    --generate-notes

ok "GitHub release created — PyPI publish will follow via Actions"

info "Done: v$NEXT"
