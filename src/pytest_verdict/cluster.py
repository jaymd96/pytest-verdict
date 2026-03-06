"""Phase 2: LLM-based failure clustering via psclaude.

Reads Phase 1 JSONL and sends failure records to Claude Code for semantic
root-cause clustering using the psclaude library.

Can be used:
  1. Integrated into pytest via --cluster (preferred -- fully automatic)
  2. As a standalone CLI: python -m pytest_verdict.cluster report.jsonl
  3. As a library: from pytest_verdict.cluster import cluster_failures
"""

import json
import sys
from importlib import resources
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a test failure analyst. You receive structured test failure data
as JSON and your job is to cluster failures by their most likely root cause.

Rules:
- Every test listed in the input MUST appear in exactly one cluster.
- Do NOT invent test names or outcomes -- use only what's in the input.
- Identify the probable root cause for each cluster. Be specific: name the
  file, function, or condition that likely caused the failures.
- Rank clusters by severity: "blocking" (prevents further work),
  "incorrect" (wrong behaviour), "cosmetic" (style/warning issues).
- Estimate fix scope: "one-liner", "localised" (one file/function),
  "cross-cutting" (multiple files/modules).
- Respond ONLY with a JSON object matching the schema below. No preamble,
  no markdown fences, no commentary.

Output schema:
{
  "clusters": [
    {
      "id": 1,
      "root_cause": "string -- specific description of the probable cause",
      "severity": "blocking | incorrect | cosmetic",
      "fix_scope": "one-liner | localised | cross-cutting",
      "affected_tests": ["test node ids"],
      "evidence": "string -- which assertion diffs or exception patterns led to this grouping",
      "suggested_fix_location": {
        "file": "path",
        "function": "name",
        "line": null
      }
    }
  ],
  "unclustered": ["any test ids that don't fit a clear cluster"]
}"""


def build_clustering_prompt(
    jsonl_lines: list[str],
) -> tuple[str, dict | None, dict | None]:
    """Build the user prompt from parsed JSONL lines.

    Returns:
        (prompt, summary_dict, warnings_dict) -- prompt is empty string if
        there are no failures to cluster.
    """
    summary = None
    failures: list[dict[str, Any]] = []
    warnings = None

    for line in jsonl_lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        record_type = obj.get("type")
        if record_type == "summary":
            summary = obj
        elif record_type == "failure":
            failures.append(obj)
        elif record_type == "warnings":
            warnings = obj

    if not failures:
        return "", summary, warnings

    prompt_parts = []

    if summary:
        prompt_parts.append(
            f"Test session: {summary['verdict']} -- "
            f"{summary.get('counts', {})} in {summary.get('duration_s', '?')}s"
        )

    prompt_parts.append(f"\n{len(failures)} failure(s):\n")
    prompt_parts.append(json.dumps(failures, indent=2, default=str))

    if warnings and warnings.get("items"):
        prompt_parts.append(
            f"\nDeduplicated warnings ({warnings['unique_count']} unique):"
        )
        prompt_parts.append(json.dumps(warnings["items"], indent=2, default=str))

    return "\n".join(prompt_parts), summary, warnings


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_cluster_response(text: str) -> dict[str, Any]:
    """Parse the LLM's clustering response.

    Handles common LLM output quirks: markdown fences, preamble text,
    JSON embedded in natural language.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse cluster response as JSON:\n{text[:500]}")


# ---------------------------------------------------------------------------
# Compact report formatter
# ---------------------------------------------------------------------------


def format_compact_report(
    summary: dict[str, Any] | None,
    clusters: dict[str, Any],
    warnings: dict[str, Any] | None = None,
) -> str:
    """Format clustered results as a compact, token-efficient report."""
    lines: list[str] = []

    if summary:
        counts = summary.get("counts", {})
        parts = [f"{v} {k}" for k, v in counts.items() if v > 0]
        lines.append(
            f"VERDICT: {summary['verdict']} | "
            f"{', '.join(parts)} | "
            f"{summary.get('duration_s', '?')}s"
        )

    cluster_list = clusters.get("clusters", [])
    if cluster_list:
        lines.append(f"\n{len(cluster_list)} failure cluster(s):\n")
        for c in cluster_list:
            severity = c.get("severity", "?")
            scope = c.get("fix_scope", "?")
            cause = c.get("root_cause", "unknown")
            tests = c.get("affected_tests", [])
            evidence = c.get("evidence", "")
            fix_loc = c.get("suggested_fix_location", {})
            fix_file = fix_loc.get("file", "?")
            fix_func = fix_loc.get("function", "")
            fix_line = fix_loc.get("line")

            fix_target = fix_file
            if fix_func:
                fix_target += f"::{fix_func}"
            if fix_line:
                fix_target += f":{fix_line}"

            lines.append(f"  [{severity}/{scope}] {cause}")
            lines.append(f"    fix -> {fix_target}")
            lines.append(f"    tests ({len(tests)}): {', '.join(tests)}")
            if evidence:
                lines.append(f"    evidence: {evidence}")
            lines.append("")

    unclustered = clusters.get("unclustered", [])
    if unclustered:
        lines.append(
            f"Unclustered ({len(unclustered)}): {', '.join(unclustered)}"
        )

    if warnings and warnings.get("items"):
        lines.append(
            f"\n{warnings['unique_count']} unique warning(s) "
            f"({warnings['total_count']} total):"
        )
        for w in warnings["items"]:
            lines.append(f"  [{w['count']}x] {w['category']}: {w['message']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main clustering function (used by both plugin and CLI)
# ---------------------------------------------------------------------------


def _get_extensions_dir() -> Path:
    """Resolve the path to bundled extensions (CLAUDE.md + skills)."""
    ref = resources.files("pytest_verdict") / "extensions"
    # resources.files returns a Traversable; for on-disk installs it's a Path
    return Path(str(ref))


def _get_skill_paths() -> list[Path]:
    """Return paths to all bundled skill markdown files."""
    skills_dir = _get_extensions_dir() / "skills"
    if skills_dir.is_dir():
        return sorted(skills_dir.glob("*.md"))
    return []


def _get_claude_md() -> Path | None:
    """Return path to the bundled CLAUDE.md, or None."""
    path = _get_extensions_dir() / "CLAUDE.md"
    return path if path.is_file() else None


def cluster_failures(
    jsonl_text: str,
    *,
    timeout: int = 120,
    skills: list[Path] | None = None,
    claude_md: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run failure clustering on JSONL text via psclaude.

    Uses bundled extensions (CLAUDE.md + skills) by default. Pass explicit
    paths to override.

    Returns (report, raw_clusters).

    Raises:
        RuntimeError: If Claude Code is not available.
        ValueError: If the LLM response can't be parsed.
    """
    from psclaude import OutputMode, PsClaude

    lines = jsonl_text.strip().splitlines()
    prompt, summary, warnings = build_clustering_prompt(lines)

    if not prompt:
        verdict = (
            "PASS" if summary and summary.get("verdict") == "PASS" else "UNKNOWN"
        )
        report = f"VERDICT: {verdict} -- no failures to cluster."
        return report, {"clusters": [], "unclustered": []}

    # Resolve extensions: use bundled defaults unless overridden
    effective_skills = skills if skills is not None else _get_skill_paths()
    effective_claude_md = claude_md if claude_md is not None else _get_claude_md()

    client = PsClaude(
        output_mode=OutputMode.TEXT,
        timeout=timeout,
        skills=effective_skills,
        claude_md=effective_claude_md,
    )
    try:
        response = client.send(prompt, system=SYSTEM_PROMPT)
    finally:
        client.cleanup()

    if not response.ok:
        raise RuntimeError(
            f"Claude Code returned exit code {response.exit_code}."
        )

    clusters = parse_cluster_response(response.text)
    report = format_compact_report(summary, clusters, warnings)

    return report, clusters


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI: python -m pytest_verdict.cluster [report.jsonl] [--timeout N]"""
    argv = argv or sys.argv[1:]

    timeout = 120
    source_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--timeout" and i + 1 < len(argv):
            timeout = int(argv[i + 1])
            i += 2
        elif argv[i] == "--check":
            from psclaude import detect

            info = detect()
            if info.available:
                print(f"Claude Code {info.version} at {info.path}", file=sys.stderr)
            else:
                print(f"Claude Code: {info.error}", file=sys.stderr)
            sys.exit(0 if info.available else 1)
        elif not argv[i].startswith("-"):
            source_path = argv[i]
            i += 1
        else:
            i += 1

    from psclaude import detect

    info = detect()
    if not info.available:
        print(f"{info.error}", file=sys.stderr)
        print("Falling back to raw JSONL output (no clustering).", file=sys.stderr)

        text = Path(source_path).read_text(encoding="utf-8") if source_path else sys.stdin.read()
        print(text)
        sys.exit(0)

    jsonl_text = (
        Path(source_path).read_text(encoding="utf-8") if source_path else sys.stdin.read()
    )

    if not jsonl_text.strip():
        print("No input.", file=sys.stderr)
        sys.exit(1)

    print(f"Claude Code {info.version}", file=sys.stderr)
    print("Clustering failures...", file=sys.stderr)

    try:
        report, clusters = cluster_failures(jsonl_text, timeout=timeout)
    except (RuntimeError, ValueError) as e:
        print(f"Clustering failed: {e}", file=sys.stderr)
        print("Raw JSONL follows:\n", file=sys.stderr)
        print(jsonl_text)
        sys.exit(1)

    print(report)
    print(json.dumps(clusters, indent=2, default=str), file=sys.stderr)


if __name__ == "__main__":
    main()
