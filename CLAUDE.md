# CLAUDE.md

## What is this?

`pytest-verdict` is a pytest plugin that produces LLM-optimised test output. Instead of human-readable terminal formatting, it emits structured JSONL designed for consumption by LLM agents — with optional failure clustering via Claude Code.

**PyPI:** `jaymd96-pytest-verdict`
**Python:** >= 3.11
**Dependencies:** pytest >= 7.0, jaymd96-psclaude >= 0.2.3

## Architecture

Two-phase design, both self-contained in the plugin:

```
Phase 1 (deterministic)          Phase 2 (LLM, optional)
─────────────────────────        ────────────────────────────
pytest hooks → TestReport        JSONL failures → psclaude → Claude Code
    ↓                                ↓
Structured JSONL:                Clustered root-cause report:
  - summary (verdict-first)        - Failures grouped by cause
  - failures (structured)          - Severity + fix scope
  - warnings (deduplicated)        - Suggested fix locations
```

Phase 2 runs only when `--cluster` is passed and Claude Code is installed. Falls back gracefully.

## Source layout

```
src/pytest_verdict/
├── __about__.py          # Version (single source of truth)
├── __init__.py           # Package root
├── __main__.py           # python -m pytest_verdict.cluster entry
├── plugin.py             # Phase 1: pytest plugin (VerdictReporter)
├── cluster.py            # Phase 2: clustering via psclaude + CLI
└── extensions/           # Bundled psclaude extensions for clustering
    ├── CLAUDE.md         # Domain instructions for test analysis
    └── skills/
        ├── cluster-failures.md
        ├── diagnose-failure.md
        └── prioritise-fixes.md

tests/
└── test_plugin.py        # 24 tests covering both phases

examples/
└── test_demo.py          # Demo test file with intentional failures

scripts/
├── release.sh            # Full release pipeline
├── check.sh              # Lint + test quality gate
└── version.sh            # Query/preview version bumps (read-only)

setup.sh                  # Dev environment bootstrap
```

## Key abstractions

| Class/Function | File | Purpose |
|---|---|---|
| `VerdictReporter` | `plugin.py` | Main pytest plugin — hooks into test lifecycle, builds JSONL |
| `FailureRecord` | `plugin.py` | Structured failure data extracted from TestReport |
| `WarningRecord` | `plugin.py` | Deduplicated warning with occurrence count |
| `cluster_failures()` | `cluster.py` | Sends JSONL to Claude Code, returns (report, clusters) |
| `build_clustering_prompt()` | `cluster.py` | Constructs the LLM prompt from parsed JSONL |
| `parse_cluster_response()` | `cluster.py` | Handles LLM output quirks (fences, preamble) |
| `format_compact_report()` | `cluster.py` | Renders clusters as token-efficient text |

## CLI flags

| Flag | Description |
|---|---|
| `--verdict` | Enable structured JSONL output |
| `--verdict-output PATH` | Write JSONL to file (default: stderr) |
| `--cluster` | Cluster failures via psclaude (implies `--verdict`) |
| `--cluster-output PATH` | Write cluster report to file (default: stderr) |
| `--cluster-timeout N` | Max seconds for Claude Code response (default: 120) |
| `--token-budget N` | Control JSONL verbosity (0 = unlimited) |

### Token budget tiers

- **0** (default): full output — all tracebacks, all warnings
- **2000**: truncated tracebacks (assertion + source-under-test only)
- **500**: failure one-liners (node_id + exception)
- **100**: verdict line only

## Quick start

```bash
# Dev setup
./setup.sh

# Run tests
hatch run test

# Lint
hatch run lint:check

# Combined quality gate
./scripts/check.sh

# See current version
./scripts/version.sh

# Preview what a patch bump would produce
./scripts/version.sh --preview
```

## Running tests in this repo

```bash
# Standard
hatch run test

# With coverage
hatch run cov

# With verdict output (dogfooding)
pytest --verdict --verdict-output report.jsonl
```

When running tests for this project, use:
```
pytest --cluster --verdict-output /tmp/verdict-report.jsonl --cluster-output /tmp/clusters.txt
```
Read `/tmp/clusters.txt` for failure analysis. If clustering fails, read `/tmp/verdict-report.jsonl` directly.

## Release process

All releases go through `scripts/release.sh`, which uses psclaude's `_version` module for PEP 440 version management.

```bash
# Preview (read-only)
./scripts/release.sh --dry-run patch

# Full release: bump → lint → test → commit → push → gh release → PyPI (via Actions)
./scripts/release.sh patch       # 0.2.1 → 0.2.2
./scripts/release.sh minor       # 0.2.1 → 0.3.0
./scripts/release.sh rc          # 0.2.1 → 0.2.2rc1
./scripts/release.sh release     # 0.2.2rc1 → 0.2.2
```

The GitHub Actions `publish.yml` workflow triggers on release creation and handles: lint → test → build → publish to PyPI.

**Do not** manually edit `__about__.py`, run `hatch publish`, or create GitHub releases by hand. The script handles the full lifecycle.

## CI

- **CI workflow** (`ci.yml`): runs lint + test on Python 3.11/3.12/3.13 on every push to main and on PRs
- **Publish workflow** (`publish.yml`): triggered by GitHub release → lint → test → build → publish to PyPI

## Code conventions

- Line length: 100
- Linter: Ruff (`E`, `F`, `I`, `UP`, `B`, `SIM`)
- Type hints everywhere
- No `from __future__ import annotations` (breaks pytest plugin introspection)
- Version lives in `src/pytest_verdict/__about__.py` — nowhere else
- JSONL output is verdict-first: the summary line is always line 1
