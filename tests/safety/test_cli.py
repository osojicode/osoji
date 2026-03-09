"""Tests for safety CLI commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from osoji.cli import main
from osoji.safety.paths import PATTERNS


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


class TestSafetyCheck:
    """Tests for 'osoji safety check' command."""

    def test_check_clean_file(self, runner, temp_dir):
        """Clean file should pass check."""
        test_file = temp_dir / "clean.py"
        test_file.write_text('print("hello")')

        result = runner.invoke(main, ["safety", "check", str(test_file)])

        assert result.exit_code == 0
        assert "passed" in result.output.lower()

    def test_check_finds_personal_path(self, runner, temp_dir):
        """File with personal path should fail check."""
        test_file = temp_dir / "bad.py"
        test_file.write_text('PATH = "C:\\Users\\jsmith\\data"')

        result = runner.invoke(main, ["safety", "check", str(test_file)])

        assert result.exit_code == 1
        assert "FAILED" in result.output

    def test_check_multiple_files(self, runner, temp_dir):
        """Should check multiple files."""
        (temp_dir / "a.py").write_text("x = 1")
        (temp_dir / "b.py").write_text("y = 2")

        result = runner.invoke(
            main, ["safety", "check", str(temp_dir / "a.py"), str(temp_dir / "b.py")]
        )

        assert result.exit_code == 0

    def test_check_verbose_output(self, runner, temp_dir):
        """Verbose flag should show more details."""
        test_file = temp_dir / "clean.py"
        test_file.write_text("x = 1")

        result = runner.invoke(main, ["-v", "safety", "check", str(test_file)])

        assert result.exit_code == 0
        assert "Files checked" in result.output


class TestSafetyPatterns:
    """Tests for 'osoji safety patterns' command."""

    def test_patterns_shows_all_patterns(self, runner):
        """Should show all pattern names and descriptions."""
        result = runner.invoke(main, ["safety", "patterns"])

        assert result.exit_code == 0
        assert "windows_user" in result.output
        assert "unix_home" in result.output
        assert "cloud_storage" in result.output
        assert "dated_folder" in result.output
        assert "personal_folder" in result.output
        assert "my_folder" in result.output

    def test_patterns_shows_regex(self, runner):
        """Should show regex patterns."""
        result = runner.invoke(main, ["safety", "patterns"])

        assert result.exit_code == 0
        assert "Regex:" in result.output

    def test_patterns_shows_count(self, runner):
        """Should show total pattern count."""
        result = runner.invoke(main, ["safety", "patterns"])

        assert result.exit_code == 0
        assert f"Total: {len(PATTERNS)} patterns" in result.output

    def test_patterns_shows_secrets_status(self, runner):
        """Should show detect-secrets installation status."""
        result = runner.invoke(main, ["safety", "patterns"])

        assert result.exit_code == 0
        assert "detect-secrets" in result.output


class TestSafetySelfTest:
    """Tests for 'osoji safety self-test' command."""

    def test_self_test_passes(self, runner):
        """Self-test should pass (osoji package should be clean)."""
        result = runner.invoke(main, ["safety", "self-test"])

        assert result.exit_code == 0
        assert "passed" in result.output.lower()

    def test_self_test_scans_package(self, runner):
        """Self-test should scan the osoji package."""
        result = runner.invoke(main, ["safety", "self-test"])

        # Should mention scanning
        assert "Scanning" in result.output or "osoji" in result.output


class TestSafetyHelp:
    """Tests for safety command help."""

    def test_safety_group_help(self, runner):
        """Safety group should have help text."""
        result = runner.invoke(main, ["safety", "--help"])

        assert result.exit_code == 0
        assert "check" in result.output
        assert "self-test" in result.output
        assert "patterns" in result.output

    def test_safety_check_help(self, runner):
        """Safety check command should have help text."""
        result = runner.invoke(main, ["safety", "check", "--help"])

        assert result.exit_code == 0
        assert "FILES" in result.output or "files" in result.output.lower()
