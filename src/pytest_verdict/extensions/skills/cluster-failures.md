# Cluster Test Failures

Analyse structured test failure data and group failures by their most likely root cause.

## When to use

When you receive pytest-verdict JSONL containing failure records and need to identify which failures share a common root cause.

## Process

1. Parse each failure record, focusing on: `source_under_test`, `assertion` diffs, `exception.type`
2. Group failures where the `source_under_test.function` is the same -- these almost certainly share a root cause
3. For failures in different functions, check if assertion patterns suggest a shared upstream issue
4. For each cluster, identify the most likely root cause and where to fix it
5. Rank clusters: blocking > incorrect > cosmetic
6. Estimate fix scope based on how many files/functions need to change

## Output schema

```json
{
  "clusters": [
    {
      "id": 1,
      "root_cause": "specific description of the probable cause",
      "severity": "blocking | incorrect | cosmetic",
      "fix_scope": "one-liner | localised | cross-cutting",
      "affected_tests": ["full test node ids"],
      "evidence": "which assertion diffs or patterns led to this grouping",
      "suggested_fix_location": {
        "file": "path",
        "function": "name",
        "line": null
      }
    }
  ],
  "unclustered": []
}
```

## Rules

- Every test in the input must appear in exactly one cluster or in unclustered
- Never invent test names -- use node_ids exactly as provided
- Be specific: "calculate_discount() missing 'platinum' key in rates dict" not "discount function has a bug"
- Evidence must reference actual data from the input (assertion values, exception messages)
