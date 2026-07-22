"""Tests for the walker's `[audit] exclude` glob exclusion (osojicode/work#90).

A project may declare repo-relative fnmatch globs under `.osoji.toml`'s
`[audit] exclude` to scope expensive analysis away from low-value trees
(e.g. a doc-heavy repo's `docs/archive/**`). This is an explicit,
user-declared scope decision -- not a silent heuristic -- so excluded paths
are dropped in BOTH the git ls-files discovery path and the rglob fallback,
alongside the existing corpus-snapshot exclusion. Excluded files are never
discovered: no shadow generation, no facts, no analysis, no findings.

Matching semantics: patterns are matched via `fnmatch.fnmatch` against the
POSIX-style path relative to the project root. `fnmatch`'s `*` already
matches any run of characters including `/` (it has no notion of a path
separator), so `**` behaves identically to a single `*` -- it's accepted
for readability/familiarity with shell-glob conventions, not because it
adds recursion `*` doesn't already have. Matching is always against the
in-root relative path, so an absolute or `../`-prefixed pattern can never
reach outside the project root -- it just never matches anything.
"""

from __future__ import annotations

import subprocess

from osoji.config import Config, PROJECT_CONFIG_FILENAME
from osoji.walker import (
    _exclude_configured_globs,
    _matches_exclude_pattern,
    clear_repo_files_cache,
    discover_files,
    list_repo_files,
)


def _write(root, rel: str, content: str = "x\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_exclude_config(root, patterns: list[str]) -> None:
    def _toml_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    quoted = ", ".join(f'"{_toml_escape(p)}"' for p in patterns)
    _write(root, PROJECT_CONFIG_FILENAME, f"[audit]\nexclude = [{quoted}]\n")


def _git_init_commit(root) -> None:
    env_kwargs = dict(cwd=root, capture_output=True, text=True, check=True)
    subprocess.run(["git", "init"], **env_kwargs)
    subprocess.run(["git", "config", "user.email", "t@example.com"], **env_kwargs)
    subprocess.run(["git", "config", "user.name", "t"], **env_kwargs)
    subprocess.run(["git", "add", "-A"], **env_kwargs)
    subprocess.run(["git", "commit", "-m", "init", "--no-gpg-sign"], **env_kwargs)


# ---------------------------------------------------------------------------
# unit: the pure glob matcher
# ---------------------------------------------------------------------------


def test_matches_exclude_pattern_simple():
    assert _matches_exclude_pattern("docs/archive/old.md", ["docs/archive/**"]) is True


def test_matches_exclude_pattern_no_match():
    assert _matches_exclude_pattern("src/app.py", ["docs/archive/**"]) is False


def test_matches_exclude_pattern_double_star_matches_nested_dirs():
    assert (
        _matches_exclude_pattern(
            "docs/archive/deep/nested/old.md", ["docs/archive/**"]
        )
        is True
    )


def test_matches_exclude_pattern_dotdot_pattern_never_matches_in_root_path():
    # A relative-to-root path never legitimately starts with "..", so a
    # pattern trying to walk upward simply never matches anything real.
    assert _matches_exclude_pattern("secret.py", ["../secret.py"]) is False


def test_exclude_configured_globs_no_patterns_is_noop(temp_dir):
    paths = [temp_dir / "a.py", temp_dir / "b.py"]
    assert _exclude_configured_globs(paths, temp_dir, []) == paths


def test_exclude_configured_globs_drops_matches(temp_dir):
    keep = temp_dir / "src" / "app.py"
    drop = temp_dir / "docs" / "archive" / "old.md"
    result = _exclude_configured_globs([keep, drop], temp_dir, ["docs/archive/**"])
    assert result == [keep]


# ---------------------------------------------------------------------------
# integration: discover_files / list_repo_files drop configured excludes,
# both discovery paths
# ---------------------------------------------------------------------------


def test_discover_files_excludes_configured_globs_rglob(temp_dir):
    """Fallback (rglob) path: respect_gitignore=False."""

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _write(temp_dir, "docs/archive/old.md", "# stale\n")
    _write(temp_dir, "docs/archive/nested/deeper.md", "# stale too\n")
    _write_exclude_config(temp_dir, ["docs/archive/**"])

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert not any(r.startswith("docs/archive/") for r in rels)


def test_discover_files_excludes_configured_globs_git(temp_dir):
    """git ls-files path: respect_gitignore=True on a real git repo."""

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _write(temp_dir, "docs/archive/old.md", "# stale\n")
    _write_exclude_config(temp_dir, ["docs/archive/**"])
    _git_init_commit(temp_dir)

    config = Config(root_path=temp_dir, respect_gitignore=True, quiet=True)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert not any(r.startswith("docs/archive/") for r in rels)


def test_discover_files_keeps_non_matching_files(temp_dir):
    _write(temp_dir, "docs/archive/old.md", "# stale\n")
    _write(temp_dir, "docs/current/guide.md", "# current\n")
    _write_exclude_config(temp_dir, ["docs/archive/**"])

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "docs/current/guide.md" not in rels  # markdown isn't a source ext anyway
    assert not any(r.startswith("docs/archive/") for r in rels)

    # Verify at the raw discovery layer (before the doc/extension filters
    # `discover_files` applies) that the non-matching doc file IS present
    # and only the excluded one was dropped.
    clear_repo_files_cache()
    raw_paths, _ = list_repo_files(config)
    raw_rels = {p.relative_to(temp_dir).as_posix() for p in raw_paths}
    assert "docs/current/guide.md" in raw_rels
    assert "docs/archive/old.md" not in raw_rels


def test_no_exclude_config_discovers_everything(temp_dir):
    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    _write(temp_dir, "src/app/other.py", "def other():\n    pass\n")

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    assert "src/app/live.py" in rels
    assert "src/app/other.py" in rels


def test_absolute_or_dotdot_pattern_does_not_escape_root(temp_dir):
    """An absolute-looking or `../`-prefixed pattern is inert, not dangerous.

    Matching is always against the path relative to the project root, so
    these patterns can't be used to reach outside the audited tree -- they
    simply never match a real in-root file.
    """

    _write(temp_dir, "src/app/live.py", "def live():\n    pass\n")
    escaping_absolute = str(temp_dir / "src" / "app" / "live.py")
    _write_exclude_config(
        temp_dir,
        ["../../etc/passwd", "../src/app/live.py", escaping_absolute],
    )

    config = Config(root_path=temp_dir, respect_gitignore=False)
    clear_repo_files_cache()
    files = discover_files(config)
    rels = {f.relative_to(temp_dir).as_posix() for f in files}

    # None of the escaping patterns matched -- the real file is still found.
    assert "src/app/live.py" in rels
