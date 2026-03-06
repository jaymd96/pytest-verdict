# pytest-verdict User Guide

How to integrate `pytest-verdict` into your codebase so LLM agents (and humans) get structured, actionable test output instead of noisy terminal logs.

## Who is this for?

You have a Python codebase using pytest. You want one or more of:

1. **Structured test output** your CI pipeline or LLM agent can parse without regex gymnastics
2. **Automatic failure clustering** that groups failures by root cause, not by test name
3. **Token-efficient test reports** for Claude Code or other LLM-assisted development workflows

## Quick start

```bash
pip install jaymd96-pytest-verdict
```

That's it. The plugin auto-registers via pytest's entry point system -- no `conftest.py` changes needed.

## Integration patterns

### 1. Claude Code project (recommended)

If you use Claude Code for development, add this to your project's `CLAUDE.md`:

```markdown
## Running tests

Always run tests with structured output:

  pytest --cluster --verdict-output /tmp/test-report.jsonl --cluster-output /tmp/clusters.txt

Read /tmp/clusters.txt for failure analysis. If clustering is unavailable, read /tmp/test-report.jsonl directly.
```

This gives Claude Code a clustered root-cause report instead of raw terminal output. Claude sees which failures share a cause, where to fix them, and in what order -- without burning tokens parsing pytest's decorative formatting.

**Prerequisites:** Claude Code CLI must be installed (`npm install -g @anthropic-ai/claude-code`).

### 2. CI pipeline integration

Add structured test output to your CI workflow so downstream tools (dashboards, LLM agents, alerting) can consume test results as data.

**GitHub Actions example:**

```yaml
- name: Run tests
  run: |
    pytest --verdict --verdict-output test-report.jsonl
  continue-on-error: true

- name: Upload structured report
  uses: actions/upload-artifact@v4
  with:
    name: test-report
    path: test-report.jsonl
```

**With clustering (requires Claude Code in CI):**

```yaml
- name: Run tests with clustering
  run: |
    pytest --cluster \
      --verdict-output test-report.jsonl \
      --cluster-output clusters.txt \
      --cluster-timeout 60
  continue-on-error: true

- name: Upload reports
  uses: actions/upload-artifact@v4
  with:
    name: test-reports
    path: |
      test-report.jsonl
      clusters.txt
```

### 3. Local development workflow

Run tests with structured output and pipe to any tool:

```bash
# Structured JSONL to a file
pytest --verdict --verdict-output report.jsonl

# Cluster failures interactively
pytest --cluster

# Cluster a previously-generated report
python -m pytest_verdict.cluster report.jsonl
```

### 4. Programmatic usage

Use the clustering API directly in scripts or custom tooling:

```python
from pytest_verdict.cluster import cluster_failures

# jsonl_text is the raw JSONL string from Phase 1
report, clusters = cluster_failures(jsonl_text, timeout=60)

print(report)  # Human-readable cluster summary

# clusters is a dict with structured data
for cluster in clusters["clusters"]:
    print(f"{cluster['severity']}: {cluster['root_cause']}")
    print(f"  Fix: {cluster['suggested_fix_location']}")
    print(f"  Tests: {cluster['affected_tests']}")
```

## Understanding the output

### Phase 1: Structured JSONL

Every line is valid JSON. Line 1 is always the summary.

```json
{"type": "summary", "verdict": "FAIL", "counts": {"passed": 42, "failed": 3, "skipped": 1}, "duration_s": 1.23}
{"type": "failure", "node_id": "tests/test_auth.py::test_validate_token", "exception": {"type": "AssertionError", "message": "Expected 'valid' but got 'expired'"}, "assertion": {"left": "'expired'", "comparator": "==", "right": "'valid'"}, "traceback": [...], "source_under_test": {"file": "src/auth/tokens.py", "line": 87, "function": "validate"}}
{"type": "warnings", "unique_count": 1, "total_count": 12, "items": [{"category": "DeprecationWarning", "message": "...", "count": 12}]}
```

Key fields for downstream consumers:

| Field | What it tells you |
|-------|-------------------|
| `summary.verdict` | PASS or FAIL -- the decision signal in the first few tokens |
| `failure.assertion` | Structured `{left, comparator, right}` -- the evaluated values, not source text |
| `failure.source_under_test` | First non-test-file traceback frame -- usually where the bug lives |
| `failure.exception.type` | Distinguishes assertion failures from runtime errors (ValueError, KeyError, etc.) |
| `warnings.items[].count` | Deduplicated warnings with occurrence counts, not 47 identical lines |

### Phase 2: Cluster report

When `--cluster` is used, failures are grouped by root cause:

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

Each cluster includes:
- **Severity**: `blocking` (ImportError, SyntaxError), `incorrect` (wrong values), `cosmetic` (warnings)
- **Fix scope**: `one-liner`, `localised` (one function), `cross-cutting` (multiple modules)
- **Suggested fix location**: file, function, and line number
- **Evidence**: which assertion diffs or exception patterns led to the grouping

## Controlling verbosity with token budgets

Use `--token-budget` to control how much output is generated. Useful when tokens are expensive or context windows are limited.

| Budget | What's included | Approximate tokens (4 failures) |
|--------|-----------------|------:|
| `0` (default) | Everything -- full tracebacks, all warnings | ~840 |
| `2000` | Truncated tracebacks (assertion line + source-under-test only) | ~500 |
| `500` | Failure one-liners (node_id + exception) | ~182 |
| `100` | Summary verdict line only | ~57 |

```bash
# Full detail for local debugging
pytest --verdict --verdict-output report.jsonl

# Compact for CI where you just need pass/fail + failure IDs
pytest --verdict --verdict-output report.jsonl --token-budget 500

# Minimal for dashboards that only need the verdict
pytest --verdict --verdict-output report.jsonl --token-budget 100
```

## CLI reference

| Flag | Description | Default |
|------|-------------|---------|
| `--verdict` | Enable structured JSONL output | off |
| `--verdict-output PATH` | Write verdict JSONL to file | stderr |
| `--cluster` | Cluster failures via Claude Code (implies `--verdict`) | off |
| `--cluster-output PATH` | Write cluster report to file | stderr |
| `--cluster-timeout N` | Max seconds for Claude Code response | 120 |
| `--token-budget N` | Control JSONL verbosity (0 = unlimited) | 0 |

## Standalone clustering CLI

```bash
# Check if Claude Code is available
python -m pytest_verdict.cluster --check

# Cluster from a file
python -m pytest_verdict.cluster report.jsonl

# Cluster from stdin
cat report.jsonl | python -m pytest_verdict.cluster

# With custom timeout
python -m pytest_verdict.cluster report.jsonl --timeout 60
```

## Requirements

- Python >= 3.11
- pytest >= 7.0
- [jaymd96-psclaude](https://pypi.org/project/jaymd96-psclaude/) >= 0.2.1 (installed automatically)
- Claude Code CLI for `--cluster` mode: `npm install -g @anthropic-ai/claude-code`

## How it works under the hood

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
    |  - Loads domain-specific CLAUDE.md and analysis skills
    |  - Sends structured failures as JSON (not terminal output)
    |  - Receives clustered root-cause analysis
    |  - Falls back gracefully if Claude Code is unavailable
    |
    v
Output: compact cluster report + raw JSONL
```

The plugin ships with bundled psclaude extensions -- a CLAUDE.md that teaches Claude how to reason about test failures, and three skills:

| Skill | Purpose |
|-------|---------|
| `cluster-failures` | Group failures by root cause with structured JSON output |
| `diagnose-failure` | Deep analysis of a single failure: test bug vs code bug, execution tracing |
| `prioritise-fixes` | Rank fix order by impact-per-effort, detect dependencies between clusters |

These load automatically with `--cluster`. You can override them programmatically via `cluster_failures(skills=..., claude_md=...)`.
