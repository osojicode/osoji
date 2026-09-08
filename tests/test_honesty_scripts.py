"""The honesty-test scoring scripts parse git diffs; content must never read as a header."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_vs_diff import parse_diff  # noqa: E402
from join_inventory_findings import removed_text_by_hunk  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def _history(temp_dir: Path) -> tuple[Path, str, str]:
    repo = temp_dir / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "docs").mkdir()
    (repo / "docs" / "sql.md").write_text("# SQL\n\n-- select all users\nSELECT * FROM users;\n\nmore\nmore\nmore\n\n++ note\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "docs" / "sql.md").write_text("# SQL\n\n-- select active users\nSELECT * FROM users WHERE active;\n\nmore\nmore\nmore\n\n++ note fixed\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "fix")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def test_parse_diff_keeps_header_lookalike_content_in_the_hunk(temp_dir):
    repo, base, head = _history(temp_dir)
    hunks, renames = parse_diff(repo, base, head)
    assert [h["path"] for h in hunks] == ["docs/sql.md", "docs/sql.md"]
    assert hunks[0]["removed_lines"] == 2 and "-- select all users" in hunks[0]["_removed_full"]
    assert hunks[1]["removed_sample"] == "++ note" and hunks[1]["added_sample"] == "++ note fixed"
    assert renames == {}


def test_removed_text_by_hunk_keeps_header_lookalike_content(temp_dir):
    repo, base, head = _history(temp_dir)
    removed = removed_text_by_hunk(repo, base, head)
    assert removed[("docs/sql.md", 3)] == "-- select all users select * from users;"
    assert removed[("docs/sql.md", 10)] == "++ note"
