# pytest-verdict: LLM-Optimised Test Output

## Problem

Test output is designed for humans scanning terminals. LLM agents consuming test
results must reverse-parse decorative formatting back into the structured data it
was derived from. This wastes tokens, introduces parsing errors, and conflates
root causes with their symptoms across duplicated tracebacks.

## Architecture

Two-phase pipeline following unix composition principles.

### Phase 1 — Deterministic Extraction (pytest plugin)

A pytest plugin that captures `TestReport` objects and emits structured JSONL.
No formatting, no decoration, no information loss. The raw fact set.

**Output contract:**
- Line 1: always the session summary (verdict + counts + duration)
- Lines 2–N: one object per failure/error, with structured assertion diffs
- Final line: deduplicated warnings with occurrence counts

**Key design decisions:**
- JSONL not JSON — streamable, each line independently parseable
- Verdict-first — the decision signal is in the first few tokens
- Assertion diffs as `{expected, actual, comparator}` triples, not rendered text
- Traceback frames include source-under-test (first non-test-file frame)
- `--token-budget` flag controls verbosity adaptively

### Phase 2 — LLM Clustering & Summarisation

Feed Phase 1's structured JSONL to a small model for semantic reasoning:
- Cluster failures by likely root cause (not string matching — causal reasoning)
- Rank clusters by severity and estimated fix complexity
- Suggest fix priorities given codebase context

**The LLM does not invent data.** It reasons over verified facts from Phase 1.
If clustering seems wrong, the raw structured data is the fallback.

### Integration with Claude Code

```
# Direct pipe — Claude Code as unix utility
pytest --agent-json | claude -p "cluster these test failures by root cause"

# Via wrapper script with budget control
pytest-verdict run --token-budget 2000 --cluster-model haiku

# In CI/CD
pytest --agent-json --token-budget 500 > test-report.jsonl
cat test-report.jsonl | claude -p "$(cat .claude/prompts/test-analysis.md)"
```

## Output Schema

### Line 1: Session Summary

```json
{
  "type": "summary",
  "verdict": "FAIL",
  "counts": {"passed": 42, "failed": 3, "skipped": 5, "error": 1},
  "duration_s": 1.23,
  "collection_errors": [],
  "python_version": "3.12.1",
  "pytest_version": "8.1.1",
  "timestamp": "2026-03-06T14:30:00Z"
}
```

### Lines 2–N: Failure Reports

```json
{
  "type": "failure",
  "node_id": "tests/test_auth.py::test_validate_token",
  "duration_s": 0.03,
  "exception": {
    "type": "AssertionError",
    "message": "Expected 'valid' but got 'expired'"
  },
  "assertion": {
    "expected": "valid",
    "actual": "expired",
    "comparator": "=="
  },
  "traceback": [
    {
      "file": "tests/test_auth.py",
      "line": 42,
      "function": "test_validate_token",
      "code": "assert result == 'valid'",
      "is_test_file": true
    },
    {
      "file": "src/auth/tokens.py",
      "line": 87,
      "function": "validate",
      "code": "return 'expired' if token.exp < now else 'valid'",
      "is_test_file": false
    }
  ],
  "source_under_test": {
    "file": "src/auth/tokens.py",
    "line": 87,
    "function": "validate"
  },
  "short_repr": "assert result == 'valid' → AssertionError"
}
```

### Final Line: Warnings

```json
{
  "type": "warnings",
  "unique_count": 3,
  "total_count": 47,
  "items": [
    {
      "category": "PendingDeprecationWarning",
      "message": "Please use `import python_multipart` instead.",
      "location": "starlette/formparsers.py:10",
      "count": 12
    }
  ]
}
```

## Token Budget Behaviour

| Budget | Includes |
|--------|----------|
| unlimited | Full output — all failures, full tracebacks, all warnings |
| > 2000 | All failures with truncated tracebacks (assertion line + source-under-test only) |
| > 500 | Summary + failure one-liners (node_id + exception message) |
| > 100 | Summary line only |

## Phase 2 Clustering Prompt

The clustering prompt instructs the LLM to:

1. Group failures by probable root cause
2. For each cluster: name the cause, list affected tests, estimate fix scope
3. Rank clusters by severity (blocking > wrong-result > cosmetic)
4. Output as structured JSON

The LLM receives deterministic facts and performs semantic reasoning.
It cannot hallucinate test names or outcomes because those are in the input.
It *can* misattribute causality — but the raw data is always available as fallback.
