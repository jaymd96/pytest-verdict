#!/bin/sh
# setup.sh — Set up the pytest-verdict repository for development.
#
# Usage:
#   ./setup.sh           Full setup (env + lint + tests)
#   ./setup.sh --dev     Dev environment only (no checks)
#
# Requirements: Python 3.11+, hatch

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# ── Helpers ──────────────────────────────────────────────────────────

info()  { printf '==> %s\n' "$1"; }
ok()    { printf '  ✓ %s\n' "$1"; }
fail()  { printf '  ✗ %s\n' "$1" >&2; exit 1; }

check_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 not found. Please install it first."
}

# ── Checks ───────────────────────────────────────────────────────────

check_python() {
    check_cmd python3
    PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
    PYMINOR=$(echo "$PYVER" | cut -d. -f2)
    if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 11 ]; }; then
        fail "Python 3.11+ required (found $PYVER)"
    fi
    ok "Python $PYVER"
}

check_hatch() {
    check_cmd hatch
    ok "hatch $(hatch --version 2>/dev/null || echo '(version unknown)')"
}

# ── Actions ──────────────────────────────────────────────────────────

setup_env() {
    info "Setting up development environment"
    check_python
    check_hatch

    info "Creating hatch environments"
    hatch env create 2>/dev/null || true
    ok "Default environment ready"

    hatch env create lint 2>/dev/null || true
    ok "Lint environment ready"
}

run_lint() {
    info "Running lint checks"
    hatch run lint:check
    ok "Lint passed"
}

run_tests() {
    info "Running tests"
    hatch run test
    ok "Tests passed"
}

# ── Main ─────────────────────────────────────────────────────────────

MODE="${1:-full}"

case "$MODE" in
    --dev)
        setup_env
        ;;
    --help|-h)
        head -7 "$0" | tail -5
        exit 0
        ;;
    full|*)
        setup_env
        run_lint
        run_tests
        ;;
esac

info "Done"
