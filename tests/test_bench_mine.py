"""Tests for the docs-fix commit miner (bench Phase 0.1, wiki specs/0005).

The miner turns a repository's history into benchmark rows: every
non-merge commit that touched only documentation and modified or removed
existing lines is a candidate "docs-fix", and each corrected hunk group at
the commit's parent is a row a checker could have flagged. Labeling
(partition / domain / kind / claim shape) is a separate step.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from bench.mine import (  # noqa: E402
    group_hunks,
    is_doc_path,
    list_docs_only_commits,
    mine_repo,
    parse_hunks,
    prefilter_reason,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(temp_dir):
    """A repo with one docs-only fix, one mixed commit, one pure addition,
    one changelog-only commit, and one wide docs commit."""
    repo = temp_dir / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shas = {}
    shas["base"] = _commit(repo, "initial", {
        "src/app.py": "def main(port=8080):\n    pass\n",
        "README.md": "# App\n\nRun `python app.py --port 8000`.\n\nSee docs/guide.md.\n",
        "docs/guide.md": "# Guide\n\nline a\nline b\nline c\nline d\nline e\nline f\nline g\nline h\nline i\nline j\n",
    })
    shas["fix"] = _commit(repo, "fix README port", {
        "README.md": "# App\n\nRun `python app.py --port 8080`.\n\nSee docs/guide.md.\n",
    })
    shas["mixed"] = _commit(repo, "rename flag", {
        "src/app.py": "def main(bind=8080):\n    pass\n",
        "README.md": "# App\n\nRun `python app.py --bind 8080`.\n\nSee docs/guide.md.\n",
    })
    shas["addition"] = _commit(repo, "docs: add note", {
        "docs/guide.md": "# Guide\n\nline a\nline b\nline c\nline d\nline e\nline f\nline g\nline h\nline i\nline j\nline k added\n",
    })
    shas["changelog"] = _commit(repo, "changelog", {"CHANGELOG.md": "## 1.0\n- stuff\n"})
    shas["wide"] = _commit(repo, "docs: sweep", {
        f"docs/p{i}.md": f"# p{i}\n\nnew {i}\n" for i in range(3)
    })
    return repo, shas


class TestIsDocPath:
    @pytest.mark.parametrize("path", ["README.md", "docs/guide.rst", "a/b.mdx", "notes.txt", "x.adoc"])
    def test_doc_extensions(self, path):
        assert is_doc_path(path)

    @pytest.mark.parametrize("path", [
        "src/app.py", "CHANGELOG.md", "changelog.d/123.md", "LICENSE.md",
        "node_modules/x/README.md", "CODE_OF_CONDUCT.md",
    ])
    def test_non_docs_and_excluded_names(self, path):
        assert not is_doc_path(path)


class TestListDocsOnlyCommits:
    def test_keeps_only_docs_only_modifying_commits(self, history):
        repo, shas = history
        commits = list_docs_only_commits(repo, since=None, max_files=20)
        found = {c.sha for c in commits}
        assert shas["fix"] in found
        assert shas["mixed"] not in found          # touched src/
        assert shas["addition"] not in found       # no deletions: pure addition
        assert shas["changelog"] not in found      # CHANGELOG is not a doc
        assert shas["base"] not in found           # touched src/

    def test_max_files_excludes_wide_commits(self, history):
        repo, shas = history
        # the wide commit is pure addition anyway; make one that modifies 3 docs
        for i in range(3):
            (repo / f"docs/p{i}.md").write_text(f"# p{i}\n\nchanged {i}\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "docs: fix three")
        wide_fix = _git(repo, "rev-parse", "HEAD")

        assert wide_fix in {c.sha for c in list_docs_only_commits(repo, since=None, max_files=3)}
        assert wide_fix not in {c.sha for c in list_docs_only_commits(repo, since=None, max_files=2)}

    def test_commit_info_fields(self, history):
        repo, shas = history
        (c,) = [c for c in list_docs_only_commits(repo, since=None, max_files=20) if c.sha == shas["fix"]]
        assert c.parent == shas["base"]
        assert c.subject == "fix README port"
        assert c.files == ["README.md"]
        assert c.date.startswith("20")


class TestParseHunks:
    def test_modification_hunk_has_minus_and_plus_text(self, history):
        repo, shas = history
        hunks = parse_hunks(repo, shas["base"], shas["fix"])
        assert len(hunks) == 1
        h = hunks[0]
        assert h.path == "README.md"
        assert h.old_start == 3 and h.old_len == 1
        assert h.minus_text == ["Run `python app.py --port 8000`."]
        assert h.plus_text == ["Run `python app.py --port 8080`."]

    def test_context_comes_from_the_parent_side(self, history):
        repo, shas = history
        (h,) = parse_hunks(repo, shas["base"], shas["fix"], context=2)
        assert h.context_before == ["# App", ""]
        assert h.context_after == ["", "See docs/guide.md."]


class TestGroupHunks:
    def _hunk(self, path, old_start, old_len=1):
        from bench.mine import Hunk
        return Hunk(path=path, old_start=old_start, old_len=old_len, new_start=old_start,
                    new_len=1, minus_text=["x"], plus_text=["y"], context_before=[], context_after=[])

    def test_adjacent_hunks_merge_into_one_row(self):
        rows = group_hunks([self._hunk("a.md", 10), self._hunk("a.md", 12)], gap=3)
        assert len(rows) == 1
        assert rows[0]["hunk_count"] == 2
        assert rows[0]["old_starts"] == [10, 12]
        assert rows[0]["hunk_seqs"] == [1, 2]

    def test_distant_hunks_stay_separate(self):
        rows = group_hunks([self._hunk("a.md", 10), self._hunk("a.md", 40)], gap=3)
        assert len(rows) == 2

    def test_different_paths_never_merge(self):
        rows = group_hunks([self._hunk("a.md", 10), self._hunk("b.md", 11)], gap=3)
        assert len(rows) == 2


class TestPrefilter:
    def test_pure_addition_is_dropped(self):
        assert prefilter_reason({"minus_text": [], "plus_text": ["new"]}) == "addition"

    def test_cosmetic_change_is_dropped(self):
        row = {"minus_text": ["Run  `app`,  now."], "plus_text": ["Run `app`, now."]}
        assert prefilter_reason(row) == "cosmetic"

    def test_substantive_change_is_kept(self):
        row = {"minus_text": ["port 8000"], "plus_text": ["port 8080"]}
        assert prefilter_reason(row) is None

    def test_deletion_is_kept(self):
        assert prefilter_reason({"minus_text": ["gone"], "plus_text": []}) is None


class TestMineRepo:
    def test_writes_commits_and_rows(self, history, temp_dir):
        repo, shas = history
        out = temp_dir / "out"

        summary = mine_repo(repo, repo_name="fixture", since=None, out_dir=out)

        commits = [json.loads(l) for l in (out / "commits.jsonl").read_text(encoding="utf-8").splitlines()]
        rows = [json.loads(l) for l in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [c["sha"] for c in commits] == [shas["fix"]]
        assert len(rows) == 1
        row = rows[0]
        assert row["row_id"] == f"fixture:{shas['fix'][:10]}:1"
        assert row["repo"] == "fixture"
        assert row["commit"] == shas["fix"] and row["parent"] == shas["base"]
        assert row["path"] == "README.md"
        assert row["minus_text"] == ["Run `python app.py --port 8000`."]
        assert row["labels"] is None
        assert summary == {"commits": 1, "rows": 1, "rows_dropped": {}}
