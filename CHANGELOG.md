# Changelog

## 0.1.0

Initial release.

- Phase 1: pytest plugin emitting structured JSONL (verdict-first, assertion diffs, deduplicated warnings, token budgets)
- Phase 2: failure clustering via psclaude (Claude Code CLI wrapper)
- Bundled extensions: CLAUDE.md, 3 skills (cluster-failures, diagnose-failure, prioritise-fixes)
- CLI: `pytest-verdict-cluster` for standalone clustering
- Flags: `--agent-json`, `--cluster`, `--agent-output`, `--cluster-output`, `--token-budget`, `--cluster-timeout`
