"""Tests for the read-only, repo-confined exploration executor (V1-3).

The executor backs Triage exploration mode: it runs read_file/grep/list_dir
against the repository root only, never writes, never escapes root, and bounds
its output so a runaway tool call can't blow the context window.
"""

from pathlib import Path

import pytest

from osoji.config import Config
from osoji.triage_exec import ExplorationExecutor


@pytest.fixture
def repo(temp_dir):
    """A small repo tree under temp_dir with a sibling secret outside root."""
    root = temp_dir / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text(
        "import os\n\ndef alpha():\n    return 'alpha-token'\n", encoding="utf-8"
    )
    (root / "pkg" / "b.py").write_text(
        "from .a import alpha\n\ndef beta():\n    return alpha()\n", encoding="utf-8"
    )
    # A secret that lives OUTSIDE the repo root — must never be readable.
    (temp_dir / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    return Config(root_path=root, respect_gitignore=False)


def test_read_file_returns_contents(repo):
    ex = ExplorationExecutor(repo)
    out = ex.read_file("pkg/a.py")
    assert "alpha-token" in out


def test_read_file_line_slice(repo):
    ex = ExplorationExecutor(repo)
    out = ex.read_file("pkg/a.py", start=3, end=4)
    assert "def alpha" in out
    assert "import os" not in out


def test_read_file_rejects_escape_relative(repo):
    ex = ExplorationExecutor(repo)
    out = ex.read_file("../secret.txt")
    assert "TOP-SECRET" not in out
    assert "error" in out.lower()


def test_read_file_rejects_escape_absolute(repo, temp_dir):
    ex = ExplorationExecutor(repo)
    out = ex.read_file(str(temp_dir / "secret.txt"))
    assert "TOP-SECRET" not in out
    assert "error" in out.lower()


def test_read_file_missing(repo):
    ex = ExplorationExecutor(repo)
    out = ex.read_file("pkg/nope.py")
    assert "error" in out.lower()


def test_read_file_caps_output(repo):
    ex = ExplorationExecutor(repo, max_file_bytes=20)
    big = repo.root_path / "pkg" / "big.py"
    big.write_text("x = 1\n" * 1000, encoding="utf-8")
    out = ex.read_file("pkg/big.py")
    assert len(out) < 600  # truncated, plus a short notice — nowhere near 6000 bytes


def test_grep_finds_matches_with_location(repo):
    ex = ExplorationExecutor(repo)
    out = ex.grep("alpha")
    # path:line: text format, both files mention alpha
    assert "pkg/a.py:" in out.replace("\\", "/")
    assert "pkg/b.py:" in out.replace("\\", "/")


def test_grep_bounds_matches(repo):
    ex = ExplorationExecutor(repo, max_grep_matches=2)
    (repo.root_path / "pkg" / "many.py").write_text(
        "alpha\n" * 50, encoding="utf-8"
    )
    out = ex.grep("alpha")
    # at most max_grep_matches result lines (a truncation notice may be appended)
    match_lines = [ln for ln in out.splitlines() if ":" in ln and "alpha" in ln]
    assert len(match_lines) <= 2


def test_grep_bad_regex_returns_error(repo):
    ex = ExplorationExecutor(repo)
    out = ex.grep("(unclosed")
    assert "error" in out.lower()


def test_grep_does_not_escape_root(repo):
    ex = ExplorationExecutor(repo)
    out = ex.grep("SECRET")
    assert "TOP-SECRET" not in out


def test_list_dir_lists_entries(repo):
    ex = ExplorationExecutor(repo)
    out = ex.list_dir("pkg")
    assert "a.py" in out
    assert "b.py" in out


def test_list_dir_bounds_entries(repo):
    ex = ExplorationExecutor(repo, max_list_entries=2)
    (repo.root_path / "pkg" / "c.py").write_text("c = 1\n", encoding="utf-8")
    out = ex.list_dir("pkg")
    # at most max_list_entries entry lines (a truncation notice is appended)
    entry_lines = [ln for ln in out.splitlines() if not ln.startswith("…")]
    assert len(entry_lines) <= 2
    assert "truncated" in out


def test_list_dir_rejects_escape(repo):
    ex = ExplorationExecutor(repo)
    out = ex.list_dir("..")
    assert "secret.txt" not in out
    assert "error" in out.lower()


def test_run_dispatches_by_tool_name(repo):
    ex = ExplorationExecutor(repo)
    assert "alpha-token" in ex.run("read_file", {"path": "pkg/a.py"})
    assert "pkg/a.py:" in ex.run("grep", {"pattern": "alpha"}).replace("\\", "/")
    assert "a.py" in ex.run("list_dir", {"path": "pkg"})


def test_run_unknown_tool(repo):
    ex = ExplorationExecutor(repo)
    out = ex.run("rm_rf", {"path": "/"})
    assert "error" in out.lower()
