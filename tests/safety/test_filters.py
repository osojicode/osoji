"""Tests for file filtering logic."""

from pathlib import Path

import pytest

from docstar.safety.filters import (
    BINARY_EXTENSIONS,
    CHECKABLE_EXTENSIONS,
    SKIP_DIRECTORIES,
    filter_checkable_files,
    should_check_file,
)


class TestShouldCheckFile:
    """Tests for should_check_file function."""

    def test_checks_python_files(self):
        """Should check .py files."""
        assert should_check_file(Path("src/main.py")) is True
        assert should_check_file(Path("src/types.pyi")) is True

    def test_checks_javascript_files(self):
        """Should check JavaScript/TypeScript files."""
        assert should_check_file(Path("src/app.js")) is True
        assert should_check_file(Path("src/app.ts")) is True
        assert should_check_file(Path("src/app.jsx")) is True
        assert should_check_file(Path("src/app.tsx")) is True

    def test_checks_config_files(self):
        """Should check config files."""
        assert should_check_file(Path("config.yaml")) is True
        assert should_check_file(Path("config.yml")) is True
        assert should_check_file(Path("config.json")) is True
        assert should_check_file(Path("pyproject.toml")) is True

    def test_checks_env_files(self):
        """Should check .env files (important for secrets!)."""
        assert should_check_file(Path(".env")) is True
        assert should_check_file(Path(".env.example")) is True
        assert should_check_file(Path(".env.local")) is True

    def test_checks_doc_files(self):
        """Should check documentation files."""
        assert should_check_file(Path("README.md")) is True
        assert should_check_file(Path("docs/guide.txt")) is True
        assert should_check_file(Path("docs/api.rst")) is True

    def test_checks_shell_files(self):
        """Should check shell script files."""
        assert should_check_file(Path("setup.sh")) is True
        assert should_check_file(Path("deploy.bash")) is True

    def test_skips_binary_files(self):
        """Should skip binary file extensions."""
        assert should_check_file(Path("image.png")) is False
        assert should_check_file(Path("image.jpg")) is False
        assert should_check_file(Path("app.exe")) is False
        assert should_check_file(Path("lib.dll")) is False
        assert should_check_file(Path("archive.zip")) is False

    def test_skips_git_directory(self):
        """Should skip files in .git directory."""
        assert should_check_file(Path(".git/config")) is False
        assert should_check_file(Path(".git/hooks/pre-commit")) is False
        assert should_check_file(Path(".git/objects/abc123")) is False

    def test_skips_node_modules(self):
        """Should skip files in node_modules."""
        assert should_check_file(Path("node_modules/pkg/index.js")) is False

    def test_skips_pycache(self):
        """Should skip __pycache__ directories."""
        assert should_check_file(Path("src/__pycache__/main.cpython-311.pyc")) is False

    def test_skips_venv(self):
        """Should skip virtual environment directories."""
        assert should_check_file(Path("venv/lib/python3.11/site.py")) is False
        assert should_check_file(Path(".venv/bin/activate")) is False

    def test_skips_build_directories(self):
        """Should skip build output directories."""
        assert should_check_file(Path("build/lib/pkg/main.py")) is False
        assert should_check_file(Path("dist/pkg-1.0.0.tar.gz")) is False

    def test_skips_docstar_directory(self):
        """Should skip .docstar output directory."""
        assert should_check_file(Path(".docstar/shadow/main.py.md")) is False

    def test_checks_files_without_extension(self):
        """Should check files without extension (like Makefile)."""
        assert should_check_file(Path("Makefile")) is True
        assert should_check_file(Path("Dockerfile")) is True

    def test_case_insensitive_extensions(self):
        """Extension matching should be case-insensitive."""
        assert should_check_file(Path("FILE.PY")) is True
        assert should_check_file(Path("IMAGE.PNG")) is False


class TestFilterCheckableFiles:
    """Tests for filter_checkable_files function."""

    def test_separates_checkable_and_skipped(self):
        """Should correctly separate files into checkable and skipped."""
        files = [
            Path("src/main.py"),
            Path("image.png"),
            Path("config.yaml"),
            Path(".git/config"),
            Path("README.md"),
        ]

        checkable, skipped = filter_checkable_files(files)

        assert Path("src/main.py") in checkable
        assert Path("config.yaml") in checkable
        assert Path("README.md") in checkable
        assert Path("image.png") in skipped
        assert Path(".git/config") in skipped

    def test_empty_input(self):
        """Should handle empty input."""
        checkable, skipped = filter_checkable_files([])

        assert checkable == []
        assert skipped == []

    def test_all_checkable(self):
        """Should handle all files being checkable."""
        files = [Path("a.py"), Path("b.js"), Path("c.md")]

        checkable, skipped = filter_checkable_files(files)

        assert len(checkable) == 3
        assert len(skipped) == 0

    def test_all_skipped(self):
        """Should handle all files being skipped."""
        files = [Path("a.png"), Path("b.exe"), Path(".git/config")]

        checkable, skipped = filter_checkable_files(files)

        assert len(checkable) == 0
        assert len(skipped) == 3


class TestExtensionSets:
    """Tests for extension and directory constants."""

    def test_no_overlap_between_checkable_and_binary(self):
        """CHECKABLE_EXTENSIONS and BINARY_EXTENSIONS should not overlap."""
        overlap = CHECKABLE_EXTENSIONS & BINARY_EXTENSIONS

        assert len(overlap) == 0, f"Overlapping extensions: {overlap}"

    def test_common_extensions_covered(self):
        """Common programming language extensions should be checkable."""
        common = {".py", ".js", ".ts", ".json", ".yaml", ".md", ".sh"}

        for ext in common:
            assert ext in CHECKABLE_EXTENSIONS, f"{ext} not in CHECKABLE_EXTENSIONS"

    def test_common_binaries_excluded(self):
        """Common binary extensions should be in BINARY_EXTENSIONS."""
        common = {".png", ".jpg", ".pdf", ".zip", ".exe"}

        for ext in common:
            assert ext in BINARY_EXTENSIONS, f"{ext} not in BINARY_EXTENSIONS"

    def test_common_skip_directories(self):
        """Common skip directories should be in SKIP_DIRECTORIES."""
        common = {".git", "node_modules", "__pycache__", "venv", ".venv"}

        for d in common:
            assert d in SKIP_DIRECTORIES, f"{d} not in SKIP_DIRECTORIES"
