"""Tests for pytest-verdict plugin and clustering infrastructure."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_pytest_verdict(
    test_file: Path,
    *,
    extra_args: list[str] | None = None,
    tmp_path: Path,
) -> list[dict]:
    """Run pytest with --agent-json on a test file and return parsed JSONL."""
    output_file = tmp_path / "report.jsonl"
    cmd = [
        sys.executable, "-m", "pytest",
        str(test_file),
        "--agent-json",
        "--agent-output", str(output_file),
        "-q",
        *(extra_args or []),
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    text = output_file.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.strip().splitlines()]


# ---------------------------------------------------------------------------
# Phase 1: Structured JSONL output
# ---------------------------------------------------------------------------


class TestAgentJsonOutput:

    def test_first_line_is_summary(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        summary = records[0]
        assert summary["type"] == "summary"
        assert summary["verdict"] == "FAIL"

    def test_summary_counts_correct(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        counts = records[0]["counts"]
        assert counts["passed"] == 6
        assert counts["failed"] == 4
        assert counts["skipped"] == 1

    def test_summary_has_metadata(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        summary = records[0]
        assert "duration_s" in summary
        assert "timestamp" in summary
        assert "python_version" in summary
        assert "pytest_version" in summary

    def test_failures_have_structured_exception(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        failures = [r for r in records if r["type"] == "failure"]
        assert len(failures) == 4

        for f in failures:
            assert "exception" in f
            assert "type" in f["exception"]
            assert "message" in f["exception"]

    def test_assertion_diffs_are_structured(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        failures = [r for r in records if r["type"] == "failure"]

        platinum = next(f for f in failures if "platinum" in f["node_id"])
        assert platinum["assertion"] is not None
        assert platinum["assertion"]["left"] == "0.0"
        assert platinum["assertion"]["comparator"] == "=="
        assert platinum["assertion"]["right"] == "25.0"

    def test_failures_have_traceback(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        failures = [r for r in records if r["type"] == "failure"]
        for f in failures:
            assert "traceback" in f
            assert isinstance(f["traceback"], list)
            assert len(f["traceback"]) > 0
            frame = f["traceback"][0]
            assert "file" in frame
            assert "line" in frame
            assert "is_test_file" in frame

    def test_all_lines_are_valid_json(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        for record in records:
            assert isinstance(record, dict)
            assert "type" in record

    def test_short_repr_is_single_line(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        failures = [r for r in records if r["type"] == "failure"]
        for f in failures:
            assert "\n" not in f["short_repr"]

    def test_passing_suite_produces_pass_verdict(self, tmp_path):
        test_file = tmp_path / "test_passing.py"
        test_file.write_text("def test_ok(): assert True\n")
        records = run_pytest_verdict(test_file, tmp_path=tmp_path)
        assert records[0]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Token budget tiers
# ---------------------------------------------------------------------------


class TestTokenBudget:

    def test_verdict_only_at_budget_100(self, tmp_path):
        records = run_pytest_verdict(
            EXAMPLES_DIR / "test_demo.py",
            extra_args=["--token-budget", "100"],
            tmp_path=tmp_path,
        )
        assert len(records) == 1
        assert records[0]["type"] == "summary"

    def test_failures_present_at_budget_500(self, tmp_path):
        records = run_pytest_verdict(
            EXAMPLES_DIR / "test_demo.py",
            extra_args=["--token-budget", "500"],
            tmp_path=tmp_path,
        )
        types = {r["type"] for r in records}
        assert "summary" in types
        assert "failure" in types

    def test_full_budget_includes_warnings(self, tmp_path):
        records = run_pytest_verdict(
            EXAMPLES_DIR / "test_demo.py",
            tmp_path=tmp_path,
        )
        types = {r["type"] for r in records}
        assert "warnings" in types


# ---------------------------------------------------------------------------
# Warning deduplication
# ---------------------------------------------------------------------------


class TestWarningDeduplication:

    def test_duplicate_warnings_collapsed(self, tmp_path):
        records = run_pytest_verdict(EXAMPLES_DIR / "test_demo.py", tmp_path=tmp_path)
        warnings_record = next(
            (r for r in records if r["type"] == "warnings"), None
        )
        assert warnings_record is not None
        assert warnings_record["unique_count"] <= 2
        assert warnings_record["total_count"] >= 2


# ---------------------------------------------------------------------------
# psclaude detection
# ---------------------------------------------------------------------------


try:
    import psclaude

    _has_psclaude = True
except ImportError:
    _has_psclaude = False


@pytest.mark.skipif(not _has_psclaude, reason="psclaude requires Python 3.11+")
class TestPsclaudeDetection:

    def test_detect_returns_info(self):
        info = psclaude.detect(force=True)
        assert isinstance(info, psclaude.ClaudeInfo)

    def test_detect_is_cached(self):
        info1 = psclaude.detect()
        info2 = psclaude.detect()
        assert info1 is info2


# ---------------------------------------------------------------------------
# Clustering prompt and response parsing
# ---------------------------------------------------------------------------


class TestClusterPromptConstruction:

    def test_empty_failures_returns_empty_prompt(self):
        from pytest_verdict.cluster import build_clustering_prompt

        lines = ['{"type": "summary", "verdict": "PASS", "counts": {"passed": 5}}']
        prompt, summary, warnings = build_clustering_prompt(lines)
        assert prompt == ""
        assert summary["verdict"] == "PASS"

    def test_failures_produce_prompt(self):
        from pytest_verdict.cluster import build_clustering_prompt

        lines = [
            '{"type": "summary", "verdict": "FAIL", "counts": {"failed": 1}}',
            '{"type": "failure", "node_id": "test_x::test_a",'
            ' "exception": {"type": "AssertionError", "message": "bad"}}',
        ]
        prompt, summary, warnings = build_clustering_prompt(lines)
        assert "test_x::test_a" in prompt
        assert "1 failure(s)" in prompt


class TestClusterResponseParsing:

    def test_parse_clean_json(self):
        from pytest_verdict.cluster import parse_cluster_response

        raw = '{"clusters": [{"id": 1}], "unclustered": []}'
        result = parse_cluster_response(raw)
        assert result["clusters"][0]["id"] == 1

    def test_parse_strips_markdown_fences(self):
        from pytest_verdict.cluster import parse_cluster_response

        raw = '```json\n{"clusters": [], "unclustered": []}\n```'
        result = parse_cluster_response(raw)
        assert result["clusters"] == []

    def test_parse_extracts_embedded_json(self):
        from pytest_verdict.cluster import parse_cluster_response

        raw = 'Here is the analysis:\n{"clusters": [], "unclustered": []}\nDone!'
        result = parse_cluster_response(raw)
        assert result["clusters"] == []

    def test_parse_raises_on_garbage(self):
        from pytest_verdict.cluster import parse_cluster_response

        with pytest.raises(ValueError, match="Could not parse"):
            parse_cluster_response("not json at all")


class TestCompactReportFormat:

    def test_verdict_line(self):
        from pytest_verdict.cluster import format_compact_report

        summary = {
            "verdict": "FAIL",
            "counts": {"passed": 3, "failed": 2},
            "duration_s": 1.5,
        }
        report = format_compact_report(
            summary, {"clusters": [], "unclustered": []}
        )
        assert report.startswith("VERDICT: FAIL")
        assert "1.5s" in report

    def test_cluster_details(self):
        from pytest_verdict.cluster import format_compact_report

        clusters = {
            "clusters": [
                {
                    "root_cause": "missing import",
                    "severity": "blocking",
                    "fix_scope": "one-liner",
                    "affected_tests": ["test_a", "test_b"],
                    "evidence": "ImportError in both",
                    "suggested_fix_location": {
                        "file": "app.py",
                        "function": "main",
                        "line": 10,
                    },
                }
            ],
            "unclustered": [],
        }
        report = format_compact_report(
            {"verdict": "FAIL", "counts": {"failed": 2}, "duration_s": 0.5},
            clusters,
        )
        assert "missing import" in report
        assert "blocking" in report
        assert "app.py::main:10" in report


# ---------------------------------------------------------------------------
# Cluster flag integration
# ---------------------------------------------------------------------------


class TestClusterFlag:

    def test_cluster_implies_agent_json(self, tmp_path):
        output_file = tmp_path / "report.jsonl"
        subprocess.run(
            [
                sys.executable, "-m", "pytest",
                str(EXAMPLES_DIR / "test_demo.py"),
                "--cluster",
                "--agent-output", str(output_file),
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert output_file.exists()
        records = [
            json.loads(line) for line in output_file.read_text().strip().splitlines()
        ]
        assert records[0]["type"] == "summary"
