# pytest-verdict

LLM-optimised test output for pytest. Structured JSONL, deduplicated warnings, adaptive token budgets, and automatic failure clustering via [psclaude](https://pypi.org/project/jaymd96-psclaude/).

## The idea

Test output is designed for humans scanning terminals. LLM agents consuming test results must reverse-parse decorative formatting back into structured data. This wastes tokens, introduces parsing errors, and conflates root causes with their symptoms across duplicated tracebacks.

`pytest-verdict` fixes this with a two-phase architecture:

- **Phase 1** (deterministic): a pytest plugin extracts structured JSONL from `TestReport` objects -- no formatting, no decoration, no information loss
- **Phase 2** (LLM clustering): sends failures to Claude Code via `psclaude` for semantic root-cause clustering -- grouping failures by *cause*, not by string similarity

The clustering runs with bundled extensions -- a domain-specific CLAUDE.md and three skills that teach Claude how to analyse test failures, cluster by root cause, and prioritise fixes.

## Install

```bash
pip install jaymd96-pytest-verdict
```

## Usage

### One command -- full pipeline

```bash
# Run tests with automatic failure clustering
pytest --cluster

# With output files for CI integration
pytest --cluster --verdict-output report.jsonl --cluster-output clusters.txt
```

If Claude Code is installed, you get a clustered failure report. If not, you get a clear message and the raw structured JSONL.

### Phase 1 only -- structured JSONL

```bash
# Emit structured JSONL without clustering
pytest --verdict --verdict-output report.jsonl

# Control verbosity with token budget
pytest --verdict --verdict-output report.jsonl --token-budget 500
```

### Standalone clustering

```bash
# Check if Claude Code is available
python -m pytest_verdict.cluster --check

# Cluster a previously-generated JSONL file
python -m pytest_verdict.cluster report.jsonl
```

### In CLAUDE.md for Claude Code projects

```markdown
When running tests, use:
  pytest --cluster --verdict-output /tmp/test-report.jsonl --cluster-output /tmp/clusters.txt
Read /tmp/clusters.txt for failure analysis. If clustering fails, read /tmp/test-report.jsonl directly.
```

## How it works

```
pytest run
    |
    v
Phase 1: pytest plugin hooks into TestReport objects
    |  - Extracts structured exception/assertion data
    |  - Deduplicates warnings with occurrence counts
    |  - Writes JSONL (verdict-first, one line per failure)
    |
    v
Phase 2: psclaude client (if --cluster and Claude Code is installed)
    |  - Creates isolated workspace with bundled extensions
    |  - Loads CLAUDE.md (test analysis domain instructions)
    |  - Loads skills: cluster-failures, diagnose-failure, prioritise-fixes
    |  - Sends structured failures as JSON (not terminal output)
    |  - Receives clustered root-cause analysis
    |  - Falls back to raw JSONL if unavailable
    |
    v
Output: compact cluster report + raw JSONL
```

## Bundled extensions

The package ships with psclaude extensions that configure Claude for test failure analysis:

| Extension | Purpose |
|-----------|---------|
| `extensions/CLAUDE.md` | Domain instructions: input format, key fields for root-cause analysis, reasoning principles, output requirements |
| `extensions/skills/cluster-failures.md` | Skill for grouping failures by root cause with structured JSON output |
| `extensions/skills/diagnose-failure.md` | Skill for in-depth analysis of a single failure: test bug vs code bug, execution tracing, fix suggestion |
| `extensions/skills/prioritise-fixes.md` | Skill for ranking fix order: impact-per-effort scoring, dependency detection, ordered fix plan |

These are loaded automatically when `--cluster` is used. You can override them by passing custom paths to `cluster_failures()` programmatically.

## Output schema

### JSONL (Phase 1)

Every line is valid JSON. Line 1 is always the summary.

```json
{"type": "summary", "verdict": "FAIL", "counts": {"passed": 42, "failed": 3, "skipped": 5}, "duration_s": 1.23}
{"type": "failure", "node_id": "tests/test_auth.py::test_validate_token", "exception": {"type": "AssertionError", "message": "..."}, "assertion": {"left": "'expired'", "comparator": "==", "right": "'valid'"}, "traceback": [...]}
{"type": "warnings", "unique_count": 1, "total_count": 12, "items": [{"category": "DeprecationWarning", "message": "...", "count": 12}]}
```

### Cluster report (Phase 2)

```
VERDICT: FAIL | 6 passed, 4 failed, 1 skipped | 0.22s

3 failure cluster(s):

  [incorrect/localised] validate_token() returns "expired" for expired tokens
    fix -> examples/test_demo.py::test_expired_token_returns_valid
    tests (2): test_expired_token_returns_valid, test_token_status_is_not_expired
    evidence: Both call validate_token("expired-abc"), function is correct, tests are wrong

  [incorrect/one-liner] calculate_discount() missing "platinum" tier in rates dict
    fix -> examples/test_demo.py::calculate_discount
    tests (1): test_platinum_discount

  [incorrect/one-liner] parse_config() raises ValueError on empty input
    fix -> examples/test_demo.py::parse_config
    tests (1): test_parse_empty_config
```

## Token budget tiers

| Flag | Includes | ~Tokens (4 failures) |
|------|----------|----:|
| `--token-budget 0` (default) | Full output -- all tracebacks, all warnings | ~840 |
| `--token-budget 2000` | Truncated tracebacks (assertion + source-under-test only) | ~500 |
| `--token-budget 500` | Failure one-liners (node_id + exception) | ~182 |
| `--token-budget 100` | Verdict line only | ~57 |

## CLI flags

| Flag | Description |
|------|-------------|
| `--verdict` | Enable structured JSONL output |
| `--verdict-output PATH` | Write verdict JSONL to file (default: stderr) |
| `--cluster` | Cluster failures via psclaude (implies `--verdict`) |
| `--cluster-output PATH` | Write cluster report to file (default: stderr) |
| `--cluster-timeout N` | Max seconds for Claude Code response (default: 120) |
| `--token-budget N` | Control JSONL verbosity (0 = unlimited) |

## Requirements

- Python >= 3.11
- pytest >= 7.0
- [jaymd96-psclaude](https://pypi.org/project/jaymd96-psclaude/) >= 0.2.1 (installed automatically)
- Claude Code CLI (for `--cluster`): `npm install -g @anthropic-ai/claude-code`
