#!/bin/sh
# check.sh — Run the full quality gate (lint + tests).
#
# Usage:
#   ./scripts/check.sh           Lint then test
#   ./scripts/check.sh --fix     Auto-fix lint issues, then test
#
# Exit code 0 means everything passes. Non-zero on first failure.

set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

info() { printf '==> %s\n' "$1"; }
ok()   { printf '  ✓ %s\n' "$1"; }

MODE="${1:-}"

# ── Lint ─────────────────────────────────────────────────────────────

if [ "$MODE" = "--fix" ]; then
    info "Auto-fixing lint issues"
    hatch run lint:fmt
    ok "Formatted"
    info "Re-checking lint"
fi

info "Running lint"
hatch run lint:check
ok "Lint passed"

# ── Tests ────────────────────────────────────────────────────────────

info "Running tests"
hatch run test
ok "Tests passed"

info "All checks passed"
