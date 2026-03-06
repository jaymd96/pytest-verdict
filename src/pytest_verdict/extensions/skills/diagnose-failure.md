# Diagnose Test Failure

Analyse a single test failure in depth to determine root cause, whether the bug is in the test or the code, and suggest a fix.

## When to use

When you have one specific test failure and need detailed analysis rather than clustering across many failures.

## Process

1. Read the failure record: exception type, message, assertion diff, traceback
2. Determine if this is a **test bug** or a **code bug**:
   - Test bug: the assertion expectation is wrong (test expects incorrect value)
   - Code bug: the production code returns wrong value / raises unexpected exception
3. Trace the execution path through the traceback frames
4. Identify the exact line/condition that causes the failure
5. Suggest a minimal fix with rationale

## Output format

```
DIAGNOSIS: [test-bug | code-bug | environment | flaky]
LOCATION: file:line -- function_name
CAUSE: one-line description
FIX: what to change and why

REASONING:
  - Step-by-step analysis of the failure chain
  - Reference specific values from assertion.left / assertion.right
  - Explain why this is the root cause, not a symptom
```

## Key distinctions

- `AssertionError` with structured assertion: compare left vs right to determine which is "wrong"
- `ValueError` / `TypeError` / `KeyError`: usually a code bug -- the function can't handle the input
- Same function failing in multiple tests: likely a code bug in that function
- Flaky: if the failure involves timing, network, or randomness, flag as potentially flaky
