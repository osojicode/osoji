"""Tests for .docstarignore pattern handling."""

from pathlib import Path

from docstar.config import Config
from docstar.walker import _matches_ignore


class TestPatternNormalization:
    """Test that load_docstarignore() normalizes slash patterns."""

    def test_trailing_slash_stripped(self, temp_dir):
        """experiments/ should match experiments."""
        (temp_dir / ".docstarignore").write_text("experiments/\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["experiments"]

    def test_leading_slash_stripped(self, temp_dir):
        """/experiments should match experiments."""
        (temp_dir / ".docstarignore").write_text("/experiments\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["experiments"]

    def test_both_slashes_stripped(self, temp_dir):
        """/experiments/ should match experiments."""
        (temp_dir / ".docstarignore").write_text("/experiments/\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["experiments"]

    def test_bare_pattern_unchanged(self, temp_dir):
        """experiments (no slashes) should remain unchanged."""
        (temp_dir / ".docstarignore").write_text("experiments\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["experiments"]

    def test_negation_with_trailing_slash(self, temp_dir):
        """!registry/ should remove 'registry' from default patterns."""
        (temp_dir / ".docstarignore").write_text("!registry/\n")
        config = Config(root_path=temp_dir)
        assert "registry" in config.ignore_patterns
        config.load_docstarignore()
        assert "registry" not in config.ignore_patterns

    def test_comments_and_blanks_skipped(self, temp_dir):
        (temp_dir / ".docstarignore").write_text("# comment\n\nexperiments/\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["experiments"]

    def test_slash_only_line_ignored(self, temp_dir):
        """A line that is just '/' should not produce an empty pattern."""
        (temp_dir / ".docstarignore").write_text("/\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == []

    def test_glob_patterns_preserved(self, temp_dir):
        """Glob patterns like *.log should pass through normalization."""
        (temp_dir / ".docstarignore").write_text("*.log\n")
        config = Config(root_path=temp_dir)
        patterns = config.load_docstarignore()
        assert patterns == ["*.log"]


class TestMatchesIgnore:
    """Test _matches_ignore() component matching."""

    def test_exact_component_match(self):
        path = Path("experiments/foo/bar.py")
        assert _matches_ignore(path, ["experiments"]) is not None

    def test_nested_component_match(self):
        path = Path("src/experiments/bar.py")
        assert _matches_ignore(path, ["experiments"]) is not None

    def test_no_match(self):
        path = Path("src/main/bar.py")
        assert _matches_ignore(path, ["experiments"]) is None

    def test_glob_pattern(self):
        path = Path("src/foo.egg-info/data.py")
        assert _matches_ignore(path, ["*.egg-info"]) is not None

    def test_full_path_glob(self):
        path = Path("build/output.js")
        assert _matches_ignore(path, ["build"]) is not None

    def test_returns_matched_pattern(self):
        path = Path("vendor/lib.go")
        result = _matches_ignore(path, ["vendor", "build"])
        assert result == "vendor"


class TestDiscoverFilesIgnore:
    """Integration: discover_files() respects .docstarignore."""

    def test_ignored_dir_excluded(self, temp_dir):
        """Files under an ignored directory should be excluded."""
        from docstar.walker import discover_files

        # Create source files
        src = temp_dir / "src"
        src.mkdir()
        (src / "main.py").write_text("print('hello')\n")

        exp = temp_dir / "experiments"
        exp.mkdir()
        (exp / "scratch.py").write_text("print('scratch')\n")

        # Create .docstarignore with trailing slash (gitignore convention)
        (temp_dir / ".docstarignore").write_text("experiments/\n")

        config = Config(root_path=temp_dir, respect_gitignore=False)
        files = discover_files(config)

        file_strs = [str(f.relative_to(temp_dir)) for f in files]
        assert any("main.py" in s for s in file_strs)
        assert not any("scratch.py" in s for s in file_strs)


class TestFindDocCandidatesIgnore:
    """Integration: find_doc_candidates() respects .docstarignore."""

    def test_ignored_docs_excluded(self, temp_dir):
        """Doc files under an ignored directory should be excluded."""
        from docstar.debris import find_doc_candidates

        # Create a doc in root
        (temp_dir / "README.md").write_text("# Readme\n")

        # Create a doc under experiments
        exp = temp_dir / "experiments"
        exp.mkdir()
        (exp / "notes.md").write_text("# Scratch notes\n")

        (temp_dir / ".docstarignore").write_text("experiments/\n")

        config = Config(root_path=temp_dir, respect_gitignore=False)
        candidates = find_doc_candidates(config)

        candidate_names = [c.name for c in candidates]
        assert "README.md" in candidate_names
        assert "notes.md" not in candidate_names
