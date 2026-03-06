# Prioritise Test Fixes

Given clustered test failures, produce a ranked fix plan optimised for unblocking the most tests with the least effort.

## When to use

After clustering, when you need to decide the order in which to fix failures.

## Process

1. Review each cluster's severity and fix scope
2. Score each cluster: severity_weight * affected_test_count / fix_effort
   - blocking = 3, incorrect = 2, cosmetic = 1
   - one-liner = 1, localised = 2, cross-cutting = 3
3. Sort by score descending -- highest impact per effort first
4. Identify dependencies between clusters (fixing A may also fix B)
5. Produce an ordered fix plan

## Output format

```
FIX PLAN (N clusters, M total failures):

1. [HIGH] cluster_cause -- N tests, fix_scope
   Why first: rationale
   Fix: specific action

2. [MEDIUM] cluster_cause -- N tests, fix_scope
   Why next: rationale
   Fix: specific action

DEPENDENCIES:
  - Fixing cluster 1 may resolve cluster 2 (shared upstream)
```

## Principles

- A one-liner that unblocks 5 tests is higher priority than a cross-cutting fix for 1 test
- Blocking failures always come first regardless of effort
- If two clusters share a suggested_fix_location, they may be the same root cause
- Flag if fixing one cluster might break currently-passing tests
