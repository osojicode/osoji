"""Tests for the walker's corpus-case snapshot exclusion (osojicode/work#85).

Committed corpus-case snapshot trees are frozen copies of production files.
Including them in repo discovery pollutes FactsDB cross-references (a
production file binds to its own snapshot copy) and produces non-actionable
findings, so the walker drops any file under a corpus-case snapshot root in
BOTH the git ls-files path and the rglob fallback. The exclusion keys on a
STRUCTURAL marker -- a ``case.json`` whose JSON ``schema`` starts
``corpus-case/`` -- never on a path convention like ``tests/fixtures``, so it
stays language- and layout-agnostic.
"""

from __future__ import annotations

import subprocess

from osoji.config import Config
from osoji.walker import (
    clear_repo_files_cache,
    discover_files,
    is_corpus_case_root,
    is_under_corpus_snapshot,
)


def _write(root, rel: str, content: str = "x\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _make_corpus_case(root, case_rel: str, *, schema: str = "corpus-case/1") -> None:
    """A fake corpus-case tree: ``<case_rel>/case.json`` + a ``source/`` file."""

    _write(root, f"{case_rel}/case.json", '{"schema": "%s", "slug": "x"}\n' % schema)
    _write(root, f"{case_rel}/source/src/app/frozen.py", "def frozen():\n    pass\n")


def _git_init_commit(root) -> None:
    env_kwargs = dict(cwd=root, capture_output=True, text=True, check=True)
    subprocess.run(["git", "init"], **env_kwargs)
    subprocess.run(["git", "config", "user.email", "t@example.com"], **env_kwargs)
    subprocess.run(["git", "config", "user.name", "t"], **env_kwargs)
    subprocess.run(["git", "add", "-A"], **env_kwargs)
    subprocess.run(["git", "commit", "-m", "init", "--no-gpg-sign"], **env_kwargs)


# ---------------------------------------------------------------------------
# unit: the structural-marker predicates
# ---------------------------------------------------------------------------


def test_is_corpus_case_root_true_for_corpus_schema(temp_dir):
    _write(temp_dir, "case_a/case.json", '{"schema": "corpus-case/1"}\n')
    cache: dict = {}
    assert is_corpus_case_root(temp_dir / "case_a", cache) is True
    # second call is served from cache (same answer)
    assert is_corpus_case_root(temp_dir / "case_a", cache) is True


def test_is_corpus_case_root_false_for_other_schema(temp_dir):
    _write(temp_dir, "case_b/case.json", '{"schema": "something-else/1"}\n')
    assert is_corpus_case_root(temp_dir / "case_b", {}) is False


def test_is_corpus_case_root_false_without_case_json(temp_dir):
    (temp_dir / "plain").mkdir()
    assert is_corpus_case_root(temp_dir / "plain", {}) is False


def test_is_corpus_case_root_false_for_malformed_case_json(temp_dir):
    _write(temp_dir, "case_c/case.json", "not valid json {{{\n")
    assert is_corpus_case_root(temp_dir / "case_c", {}) is False


def test_is_under_corpus_snapshot_walks_ancestors(temp_dir):
    _make_corpus_case(temp_dir, "corpus/case_a")
    deep = temp_dir / "corpus" / "case_a" / "source" / "src" / "app" / "frozen.py"
    assert is_under_corpus_snapshot(deep, temp_dir, {}) is True
    # a file NOT under any snapshot root
    other = temp_dir / "src" / "app" / "live.py"
    assert is_under_corpus_snapshot(other, temp_dir, {}) is False


# ---------------------------------------------------------------------------
# integration: discover_files drops snapshot files, both discovery paths
# ---------------------------------------------------------------------------


def test_discover_files_excludes_snapshot_subtree_rglob(temp_dir):
    """Fallback (rglob) path: respect_gitignore=False."""

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _make_corpus_case(temp_dir, "tests/fixtures/prompt_regression/dead_symbol/case_001")

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert not any("case_001/source" in r for r in rels)
    assert "tests/fixtures/prompt_regression/dead_symbol/case_001/source/src/app/frozen.py" not in rels


def test_discover_files_excludes_snapshot_subtree_git(temp_dir):
    """git ls-files path: respect_gitignore=True on a real git repo."""

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _make_corpus_case(temp_dir, "tests/fixtures/prompt_regression/dead_symbol/case_001")
    _git_init_commit(temp_dir)

    config = Config(root_path=temp_dir, respect_gitignore=True, quiet=True)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert not any("case_001/source" in r for r in rels)


def test_discover_files_keeps_non_corpus_case_json_subtree(temp_dir):
    """A ``case.json`` with a NON-corpus schema is not a snapshot root, so its
    subtree is audited normally."""

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _make_corpus_case(temp_dir, "data/not_a_case", schema="something-else/1")

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert "data/not_a_case/source/src/app/frozen.py" in rels
