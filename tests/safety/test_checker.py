"""Tests for the safety checker orchestrator."""

from pathlib import Path

import pytest

from osoji.safety.checker import (
    check_file,
    check_files,
    format_check_result,
)
from osoji.safety.models import CheckResult, PathFinding


class TestCheckFile:
    """Tests for check_file function."""

    def test_finds_personal_path(self, temp_dir):
        """Should detect personal paths in a file."""
        test_file = temp_dir / "config.py"
        test_file.write_text('PATH = "/home/jsmith/projects"')

        result = check_file(test_file)

        assert not result.passed
        assert len(result.path_findings) == 1
        assert result.files_checked == 1

    def test_safe_file_passes(self, temp_dir):
        """Clean files should pass."""
        test_file = temp_dir / "clean.py"
        test_file.write_text('import os\nprint("hello")')

        result = check_file(test_file)

        assert result.passed
        assert result.files_checked == 1
        assert len(result.path_findings) == 0

    def test_skips_binary_file(self, temp_dir):
        """Binary files should be skipped."""
        test_file = temp_dir / "image.png"
        test_file.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = check_file(test_file)

        assert result.passed
        assert result.files_checked == 0
        assert result.files_skipped == 1

    def test_handles_nonexistent_file(self, temp_dir):
        """Should handle non-existent files gracefully."""
        result = check_file(temp_dir / "nonexistent.py")

        assert result.files_checked == 0
        assert len(result.errors) == 1

    def test_multiple_findings_in_file(self, temp_dir):
        """Should find multiple paths in the same file."""
        test_file = temp_dir / "config.py"
        test_file.write_text(
            """
PATH1 = "/home/jsmith/data"
PATH2 = "C:\\Users\\alice\\docs"
"""
        )

        result = check_file(test_file)

        assert not result.passed
        assert len(result.path_findings) == 2


class TestCheckFiles:
    """Tests for check_files function."""

    def test_checks_multiple_files(self, temp_dir):
        """Should check multiple files."""
        (temp_dir / "a.py").write_text("x = 1")
        (temp_dir / "b.py").write_text('y = "/home/user/data"')  # excluded user

        result = check_files([temp_dir / "a.py", temp_dir / "b.py"])

        assert result.files_checked == 2

    def test_aggregates_findings(self, temp_dir):
        """Should aggregate findings from multiple files."""
        (temp_dir / "a.py").write_text('x = "/home/jsmith/a"')
        (temp_dir / "b.py").write_text('y = "/home/alice/b"')

        result = check_files([temp_dir / "a.py", temp_dir / "b.py"])

        assert len(result.path_findings) == 2
        assert result.files_checked == 2

    def test_filters_binary_files(self, temp_dir):
        """Should filter out binary files."""
        (temp_dir / "code.py").write_text("x = 1")
        (temp_dir / "image.png").write_bytes(b"\x89PNG")

        result = check_files([temp_dir / "code.py", temp_dir / "image.png"])

        assert result.files_checked == 1
        assert result.files_skipped == 1

    def test_empty_list(self):
        """Should handle empty file list."""
        result = check_files([])

        assert result.passed
        assert result.files_checked == 0


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_passed_when_empty(self):
        """Empty result should be considered passed."""
        result = CheckResult()

        assert result.passed

    def test_not_passed_with_path_findings(self):
        """Result with path findings should not pass."""
        finding = PathFinding(
            file=Path("test.py"),
            line_number=1,
            line_content="test",
            pattern_name="test",
            match="test",
        )
        result = CheckResult(path_findings=[finding])

        assert not result.passed

    def test_finding_count(self):
        """finding_count should sum path and secret findings."""
        result = CheckResult(
            path_findings=[
                PathFinding(
                    file=Path("a.py"),
                    line_number=1,
                    line_content="",
                    pattern_name="",
                    match="",
                ),
                PathFinding(
                    file=Path("b.py"),
                    line_number=1,
                    line_content="",
                    pattern_name="",
                    match="",
                ),
            ],
        )

        assert result.finding_count == 2

    def test_merge_combines_results(self):
        """merge should combine two CheckResults."""
        r1 = CheckResult(files_checked=1, files_skipped=2)
        r2 = CheckResult(files_checked=3, files_skipped=4)

        merged = r1.merge(r2)

        assert merged.files_checked == 4
        assert merged.files_skipped == 6

    def test_summary_passed(self):
        """Summary for passed result."""
        result = CheckResult(files_checked=5)

        assert "passed" in result.summary().lower()
        assert "5" in result.summary()

    def test_summary_failed(self):
        """Summary for failed result."""
        result = CheckResult(
            files_checked=3,
            path_findings=[
                PathFinding(
                    file=Path("a.py"),
                    line_number=1,
                    line_content="",
                    pattern_name="",
                    match="",
                )
            ],
        )

        assert "failed" in result.summary().lower()
        assert "1" in result.summary()  # 1 issue


class TestFormatCheckResult:
    """Tests for format_check_result function."""

    def test_format_passed(self):
        """Should format passed result."""
        result = CheckResult(files_checked=5)

        output = format_check_result(result)

        assert "passed" in output.lower()
        assert "no issues" in output.lower()

    def test_format_failed_with_paths(self, temp_dir):
        """Should format failed result with path findings."""
        result = CheckResult(
            files_checked=1,
            path_findings=[
                PathFinding(
                    file=Path("config.py"),
                    line_number=15,
                    line_content='PATH = "/home/jsmith/"',
                    pattern_name="unix_home",
                    match="/home/jsmith/",
                )
            ],
        )

        output = format_check_result(result)

        assert "FAILED" in output
        assert "config.py" in output
        assert "15" in output
        assert "unix_home" in output

    def test_verbose_includes_counts(self):
        """Verbose mode should include file counts."""
        result = CheckResult(files_checked=5, files_skipped=3)

        output = format_check_result(result, verbose=True)

        assert "5" in output
        assert "3" in output

    def test_includes_remediation_suggestions(self):
        """Failed output should include remediation suggestions."""
        result = CheckResult(
            files_checked=1,
            path_findings=[
                PathFinding(
                    file=Path("x.py"),
                    line_number=1,
                    line_content="",
                    pattern_name="",
                    match="",
                )
            ],
        )

        output = format_check_result(result)

        assert "Replace personal paths" in output or "generic alternatives" in output
        assert "--no-verify" in output  # Emergency bypass
