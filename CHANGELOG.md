# Changelog

## 0.2.0

Consistent naming: standardise all CLI flags and internals on `verdict`.

**Breaking changes:**
- `--agent-json` renamed to `--verdict`
- `--agent-output` renamed to `--verdict-output`
- Internal class `AgentReporter` renamed to `VerdictReporter`
- Plugin registration name changed from `agent_reporter` to `verdict_reporter`

No changes to JSON output schema, `--cluster*` flags, or `--token-budget`.

## 0.1.0

Initial release.

- Phase 1: pytest plugin emitting structured JSONL (verdict-first, assertion diffs, deduplicated warnings, token budgets)
- Phase 2: failure clustering via psclaude (Claude Code CLI wrapper)
- Bundled extensions: CLAUDE.md, 3 skills (cluster-failures, diagnose-failure, prioritise-fixes)
- CLI: `pytest-verdict-cluster` for standalone clustering
- Flags: `--verdict`, `--cluster`, `--verdict-output`, `--cluster-output`, `--token-budget`, `--cluster-timeout`
