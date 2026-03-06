"""pytest-verdict: LLM-optimised test output.

A pytest plugin that emits structured JSONL designed for consumption by
LLM agents rather than human eyes. Eliminates decorative formatting,
deduplicates warnings, structures assertion diffs as data, and respects
a configurable token budget.

Two-phase architecture, self-contained:
  Phase 1 -- deterministic extraction of structured test data (always runs)
  Phase 2 -- LLM clustering of failures by root cause via psclaude
             (runs when --cluster is passed and Claude Code is installed)

Usage:
  # Phase 1 only -- structured JSONL
  pytest --agent-json --agent-output report.jsonl

  # Full pipeline -- extraction + clustering in one command
  pytest --agent-json --cluster
"""

import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from _pytest.reports import TestReport

# ---------------------------------------------------------------------------
# Token budget tiers
# ---------------------------------------------------------------------------

BUDGET_FULL = float("inf")
BUDGET_TRUNCATED = 2000  # tracebacks trimmed to assertion + source-under-test
BUDGET_ONELINER = 500  # failure one-liners only
BUDGET_VERDICT = 100  # summary line only


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("agent", "LLM agent output")
    group.addoption(
        "--agent-json",
        action="store_true",
        default=False,
        help="Emit structured JSONL output optimised for LLM consumption.",
    )
    group.addoption(
        "--agent-output",
        metavar="PATH",
        default=None,
        help="Write agent JSONL to a file instead of stderr.",
    )
    group.addoption(
        "--token-budget",
        type=int,
        default=0,
        help=(
            "Approximate token budget for output. Controls verbosity: "
            ">2000 includes truncated tracebacks, >500 includes failure "
            "one-liners, >100 includes summary only. 0 means unlimited."
        ),
    )
    group.addoption(
        "--cluster",
        action="store_true",
        default=False,
        help=(
            "Cluster test failures by root cause using Claude Code CLI. "
            "Implies --agent-json. Requires Claude Code to be installed "
            "(falls back to raw JSONL if unavailable)."
        ),
    )
    group.addoption(
        "--cluster-timeout",
        type=int,
        default=120,
        help="Max seconds to wait for Claude Code clustering response (default: 120).",
    )
    group.addoption(
        "--cluster-output",
        metavar="PATH",
        default=None,
        help="Write cluster report to a file (default: stderr).",
    )


def pytest_configure(config: pytest.Config) -> None:
    # --cluster implies --agent-json
    wants_agent = config.getoption("agent_json", default=False)
    wants_cluster = config.getoption("cluster", default=False)

    if wants_agent or wants_cluster:
        plugin = AgentReporter(config, cluster=wants_cluster)
        config.pluginmanager.register(plugin, "agent_reporter")


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


@dataclass
class WarningRecord:
    category: str
    message: str
    location: str
    count: int = 1


@dataclass
class FailureRecord:
    node_id: str
    duration: float
    exception_type: str
    exception_message: str
    assertion: dict[str, Any] | None
    traceback_frames: list[dict[str, Any]]
    source_under_test: dict[str, Any] | None
    short_repr: str
    outcome: str  # "failed" or "error"


@dataclass(eq=False)
class AgentReporter:
    config: pytest.Config
    cluster: bool = False
    failures: list[FailureRecord] = field(default_factory=list)
    outcomes: Counter = field(default_factory=Counter)
    warnings_seen: dict[str, WarningRecord] = field(default_factory=dict)
    collection_errors: list[str] = field(default_factory=list)
    session_start: float = field(default_factory=time.monotonic)
    _test_durations: dict[str, float] = field(default_factory=dict)

    @property
    def token_budget(self) -> float:
        budget = self.config.getoption("token_budget", default=0)
        return float("inf") if budget == 0 else budget

    @property
    def output_path(self) -> str | None:
        return self.config.getoption("agent_output", default=None)

    @property
    def cluster_timeout(self) -> int:
        return self.config.getoption("cluster_timeout", default=120)

    @property
    def cluster_output_path(self) -> str | None:
        return self.config.getoption("cluster_output", default=None)

    # -- hooks ---------------------------------------------------------------

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo
    ):
        outcome = yield
        report: TestReport = outcome.get_result()

        if report.when == "call":
            self.outcomes[report.outcome] += 1

            if report.outcome in ("failed",):
                self.failures.append(self._extract_failure(report, item))

        elif report.when == "setup" and report.outcome == "skipped":
            self.outcomes["skipped"] += 1

        elif report.when in ("setup", "teardown") and report.outcome == "failed":
            self.outcomes["error"] += 1
            self.failures.append(self._extract_failure(report, item, outcome_type="error"))

    def pytest_warning_recorded(
        self,
        warning_message,
        when: str,
        nodeid: str,
        location: tuple | None,
    ) -> None:
        cat_cls = warning_message.category
        cat = cat_cls.__name__ if isinstance(cat_cls, type) else str(cat_cls)
        msg = str(warning_message.message)
        loc = f"{warning_message.filename}:{warning_message.lineno}"

        key = f"{cat}::{msg}"
        if key in self.warnings_seen:
            self.warnings_seen[key].count += 1
        else:
            self.warnings_seen[key] = WarningRecord(
                category=cat, message=msg, location=loc
            )

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.collection_errors.append(str(report.longrepr))

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        duration = time.monotonic() - self.session_start
        lines = self._build_output(duration, exitstatus)

        output_text = "\n".join(lines) + "\n"

        # Phase 1: write structured JSONL
        if self.output_path:
            Path(self.output_path).write_text(output_text, encoding="utf-8")
        else:
            sys.stderr.write(output_text)

        # Phase 2: cluster failures via psclaude (if requested and there are failures)
        if self.cluster and self.failures:
            self._run_clustering(output_text)
        elif self.cluster and not self.failures:
            self._write_cluster_output("VERDICT: PASS -- no failures to cluster.\n")

    def _run_clustering(self, jsonl_text: str) -> None:
        """Run Phase 2 clustering via psclaude."""
        try:
            from psclaude import detect
        except ImportError:
            self._write_cluster_output(
                "Clustering skipped: jaymd96-psclaude not installed.\n"
                "Install with: pip install jaymd96-psclaude\n"
            )
            return

        from pytest_verdict.cluster import cluster_failures

        info = detect()
        if not info.available:
            fallback_msg = (
                f"Claude Code not available: {info.error}\n"
                "Clustering skipped. Raw JSONL was written above.\n"
                "Install Claude Code for automatic failure clustering:\n"
                "  npm install -g @anthropic-ai/claude-code\n"
            )
            self._write_cluster_output(fallback_msg)
            return

        sys.stderr.write(
            f"Claude Code {info.version} -- clustering {len(self.failures)} failure(s)...\n"
        )

        try:
            report, clusters = cluster_failures(
                jsonl_text,
                timeout=self.cluster_timeout,
            )

            full_output = report + "\n"
            full_output += "\n---CLUSTERS_JSON---\n"
            full_output += json.dumps(clusters, indent=2, default=str)
            full_output += "\n"

            self._write_cluster_output(full_output)

        except (RuntimeError, ValueError) as exc:
            error_msg = (
                f"Clustering failed: {exc}\n"
                "Raw JSONL was written above -- you can cluster manually:\n"
                "  python -m pytest_verdict.cluster report.jsonl\n"
            )
            self._write_cluster_output(error_msg)

    def _write_cluster_output(self, text: str) -> None:
        if self.cluster_output_path:
            Path(self.cluster_output_path).write_text(text, encoding="utf-8")
        else:
            sys.stderr.write(text)

    def pytest_terminal_summary(self, terminalreporter) -> None:
        pass

    # -- extraction ----------------------------------------------------------

    def _extract_failure(
        self, report: TestReport, item: pytest.Item, *, outcome_type: str = "failed"
    ) -> FailureRecord:
        exc_type, exc_msg = self._parse_exception(report)
        assertion = self._parse_assertion(report)
        frames = self._parse_traceback(report)
        source = self._find_source_under_test(frames, item)

        exc_msg_clean = exc_msg.split("\n")[0].strip()
        short = self._make_short_repr(report, exc_type, exc_msg_clean)

        return FailureRecord(
            node_id=report.nodeid,
            duration=report.duration,
            exception_type=exc_type,
            exception_message=exc_msg_clean,
            assertion=assertion,
            traceback_frames=frames,
            source_under_test=source,
            short_repr=short,
            outcome=outcome_type,
        )

    def _parse_exception(self, report: TestReport) -> tuple[str, str]:
        if not hasattr(report, "longrepr") or not report.longrepr:
            return "Unknown", ""

        longrepr = report.longrepr

        if hasattr(longrepr, "chain"):
            for _repr_traceback, repr_crash, _ in longrepr.chain:
                if repr_crash:
                    msg = repr_crash.message
                    if ": " in msg:
                        exc_type, exc_msg = msg.split(": ", 1)
                        return exc_type.strip(), exc_msg.strip()
                    if msg.strip().startswith("assert "):
                        return "AssertionError", msg.strip()
                    return msg.strip(), ""

        text = str(longrepr)
        exc_match = re.search(
            r"^E\s+(\w+Error|\w+Exception|\w+Warning): (.+)$", text, re.MULTILINE
        )
        if exc_match:
            return exc_match.group(1), exc_match.group(2).strip()

        lines = text.strip().splitlines()
        if lines:
            last = lines[-1].strip()
            if ": " in last:
                exc_type, exc_msg = last.split(": ", 1)
                return exc_type.strip(), exc_msg.strip()
            return last, ""

        return "Unknown", ""

    def _parse_assertion(self, report: TestReport) -> dict[str, Any] | None:
        if not hasattr(report, "longrepr") or not report.longrepr:
            return None

        text = str(report.longrepr)

        for pattern in [
            r"E\s+assert\s+(.+?)\s+(==|!=|<|>|<=|>=|is not|is|not in|in)\s+(.+?)(?:\s*$)",
        ]:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                left = match.group(1).strip()
                right = match.group(3).strip()
                if "  #" in right:
                    right = right.split("  #")[0].strip()
                return {
                    "left": left,
                    "comparator": match.group(2).strip(),
                    "right": right,
                }

        for pattern in [
            r">\s+assert\s+(.+?)\s+(==|!=|<|>|<=|>=|is not|is|not in|in)\s+(.+?)(?:,|\s*$)",
        ]:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                left = match.group(1).strip()
                right = match.group(3).strip()
                if "  #" in right:
                    right = right.split("  #")[0].strip()
                return {
                    "left": left,
                    "comparator": match.group(2).strip(),
                    "right": right,
                }

        return None

    def _parse_traceback(self, report: TestReport) -> list[dict[str, Any]]:
        frames = []

        if not hasattr(report, "longrepr") or not report.longrepr:
            return frames

        longrepr = report.longrepr

        if hasattr(longrepr, "chain"):
            for repr_traceback, _repr_crash, _ in longrepr.chain:
                if repr_traceback and hasattr(repr_traceback, "reprentries"):
                    for entry in repr_traceback.reprentries:
                        frame = self._entry_to_frame(entry)
                        if frame:
                            frames.append(frame)

        elif hasattr(longrepr, "reprentries"):
            for entry in longrepr.reprentries:
                frame = self._entry_to_frame(entry)
                if frame:
                    frames.append(frame)

        return frames

    def _entry_to_frame(self, entry) -> dict[str, Any] | None:
        if not hasattr(entry, "reprfileloc"):
            return None

        fileloc = entry.reprfileloc
        if not fileloc:
            return None

        filepath = str(fileloc.path) if fileloc.path else ""
        is_test = self._is_test_file(filepath)

        code = ""
        if hasattr(entry, "lines") and entry.lines:
            source_lines = []
            for line in entry.lines:
                stripped = line.lstrip()
                if stripped.startswith("E ") or stripped.startswith("^"):
                    continue
                clean = line.replace(">", " ", 1) if line.lstrip().startswith(">") else line
                source_lines.append(clean.rstrip())
            code = "\n".join(s for s in source_lines if s.strip()).strip()

        return {
            "file": filepath,
            "line": fileloc.lineno,
            "function": fileloc.message if hasattr(fileloc, "message") else "",
            "code": code,
            "is_test_file": is_test,
        }

    def _is_test_file(self, filepath: str) -> bool:
        p = Path(filepath)
        name = p.name.lower()
        parts = [part.lower() for part in p.parts]

        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or name == "conftest.py"
            or "tests" in parts
            or "test" in parts
        )

    def _find_source_under_test(
        self, frames: list[dict[str, Any]], item: pytest.Item
    ) -> dict[str, Any] | None:
        for frame in reversed(frames):
            if not frame.get("is_test_file", True):
                return {
                    "file": frame["file"],
                    "line": frame["line"],
                    "function": frame.get("function", ""),
                }
        return None

    def _make_short_repr(
        self, report: TestReport, exc_type: str, exc_msg: str
    ) -> str:
        first_line = exc_msg.split("\n")[0].strip()
        if len(first_line) > 120:
            first_line = first_line[:120] + "..."
        return f"{exc_type}: {first_line}" if first_line else exc_type

    # -- output building -----------------------------------------------------

    def _build_output(self, duration: float, exitstatus: int) -> list[str]:
        budget = self.token_budget
        lines: list[str] = []

        verdict = "PASS" if exitstatus == 0 else "FAIL"
        summary = {
            "type": "summary",
            "verdict": verdict,
            "exit_code": exitstatus,
            "counts": dict(self.outcomes),
            "duration_s": round(duration, 3),
            "timestamp": datetime.now(UTC).isoformat(),
            "python_version": (
                f"{sys.version_info.major}.{sys.version_info.minor}"
                f".{sys.version_info.micro}"
            ),
            "pytest_version": pytest.__version__,
        }
        if self.collection_errors:
            summary["collection_errors"] = self.collection_errors

        lines.append(json.dumps(summary, default=str))

        if budget <= BUDGET_VERDICT:
            return lines

        for failure in self.failures:
            record: dict[str, Any] = {
                "type": "failure",
                "node_id": failure.node_id,
                "outcome": failure.outcome,
                "duration_s": round(failure.duration, 4),
                "exception": {
                    "type": failure.exception_type,
                    "message": failure.exception_message,
                },
                "short_repr": failure.short_repr,
            }

            if budget >= BUDGET_ONELINER:
                if failure.assertion:
                    record["assertion"] = failure.assertion
                if failure.source_under_test:
                    record["source_under_test"] = failure.source_under_test

            if budget >= BUDGET_TRUNCATED and failure.traceback_frames:
                key_frames = self._select_key_frames(failure)
                record["traceback"] = key_frames

            if budget == BUDGET_FULL or budget > BUDGET_TRUNCATED:
                record["traceback"] = failure.traceback_frames

            lines.append(json.dumps(record, default=str))

        if self.warnings_seen and budget > BUDGET_VERDICT:
            warnings_data = {
                "type": "warnings",
                "unique_count": len(self.warnings_seen),
                "total_count": sum(w.count for w in self.warnings_seen.values()),
                "items": [
                    {
                        "category": w.category,
                        "message": w.message,
                        "location": w.location,
                        "count": w.count,
                    }
                    for w in sorted(
                        self.warnings_seen.values(),
                        key=lambda w: w.count,
                        reverse=True,
                    )
                ],
            }
            lines.append(json.dumps(warnings_data, default=str))

        return lines

    def _select_key_frames(self, failure: FailureRecord) -> list[dict[str, Any]]:
        key = []
        seen_files = set()

        for frame in reversed(failure.traceback_frames):
            if frame.get("is_test_file"):
                key.append(frame)
                seen_files.add(frame["file"])
                break

        for frame in reversed(failure.traceback_frames):
            if not frame.get("is_test_file") and frame["file"] not in seen_files:
                key.append(frame)
                break

        return key
