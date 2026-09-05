"""Tests for the benchmark runner (bench Phase 0, wiki specs/0005).

The runner checks a working tree out at each docs-fix commit's parent,
refreshes osoji's substrate there, analyses only the documents the fix
touched, and writes the findings as one JSON per parent for ``bench.score``.
The expensive steps (substrate refresh, document analysis) are injected so
the orchestration is testable without an LLM.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from bench.run import issues_from_results, run_parents, select_parents  # noqa: E402
from osoji.doc_analysis import DocAnalysisResult, DocFinding  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _row(row_id, parent, path, *, date, partition="correction", domain="checkout"):
    return {"row_id": row_id, "repo": "x", "commit": "c" * 40, "parent": parent, "commit_date": date,
            "path": path, "old_start": 3, "old_len": 1, "minus_text": ["old"], "plus_text": ["new"],
            "labels": {"r1": {"partition": partition, "domain": domain, "kind": "false_statement",
                              "claim_shape": "behaviour", "claim": "c", "confidence": 0.8}}}


class TestSelectParents:
    def test_groups_counting_rows_by_parent_newest_first(self):
        rows = [
            _row("a", "p1", "README.md", date="2026-01-01T00:00:00Z"),
            _row("b", "p1", "docs/x.md", date="2026-01-01T00:00:00Z"),
            _row("c", "p2", "README.md", date="2026-03-01T00:00:00Z"),
            _row("d", "p3", "README.md", date="2026-02-01T00:00:00Z", partition="addition"),
        ]
        selected = select_parents(rows, reader="r1", max_parents=None)
        assert [p["parent"] for p in selected] == ["p2", "p1"]
        assert selected[1]["docs"] == ["README.md", "docs/x.md"]

    def test_max_parents_truncates(self):
        rows = [_row("a", "p1", "a.md", date="2026-01-01T00:00:00Z"),
                _row("b", "p2", "b.md", date="2026-02-01T00:00:00Z")]
        assert [p["parent"] for p in select_parents(rows, reader="r1", max_parents=1)] == ["p2"]


class TestSnapshotPlan:
    """One substrate per repo: rows whose removed text is still present at a
    chosen snapshot are evaluated there instead of at their own parents."""

    @pytest.fixture
    def repo(self, temp_dir):
        from bench.run import _git as git  # same helper the runner uses
        repo = temp_dir / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        base = _commit(repo, "base", {"README.md": "# A\n\nwrong one\nwrong two\n", "docs/x.md": "# X\n\nstale\n"})
        fix1 = _commit(repo, "fix one", {"README.md": "# A\n\nright one\nwrong two\n"})
        fix2 = _commit(repo, "fix x", {"docs/x.md": "# X\n\nfresh\n"})
        return repo, base, fix1, fix2

    def test_rows_present_verbatim_at_snapshot_are_selected(self, repo):
        from bench.run import snapshot_plan
        repo_path, base, fix1, fix2 = repo
        rows = [
            {**_row("a", base, "README.md", date="2026-01-01T00:00:00Z"), "minus_text": ["wrong one"]},
            {**_row("b", fix1, "README.md", date="2026-02-01T00:00:00Z"), "minus_text": ["wrong two"]},
            {**_row("c", fix1, "docs/x.md", date="2026-02-01T00:00:00Z"), "minus_text": ["stale"]},
        ]
        # snapshot = fix1: "wrong one" is already fixed there, "wrong two" and "stale" are still present
        plan, selected = snapshot_plan(repo_path, fix1, rows, reader="r1")

        assert plan == [{"parent": fix1, "date": None, "docs": ["README.md", "docs/x.md"], "rows": 2}]
        assert selected == {"b": fix1, "c": fix1}

    def test_whitespace_differences_do_not_break_presence(self, repo):
        from bench.run import snapshot_plan
        repo_path, base, fix1, fix2 = repo
        rows = [{**_row("b", fix1, "README.md", date="x"), "minus_text": ["  wrong   two "]}]
        _, selected = snapshot_plan(repo_path, fix1, rows, reader="r1")
        assert selected == {"b": fix1}

    def test_best_snapshot_picks_the_parent_where_most_rows_are_present(self, repo):
        from bench.run import best_snapshot
        repo_path, base, fix1, fix2 = repo
        rows = [
            {**_row("a", base, "README.md", date="2026-01-01T00:00:00Z"), "minus_text": ["wrong one"]},
            {**_row("b", fix1, "README.md", date="2026-02-01T00:00:00Z"), "minus_text": ["wrong two"]},
            {**_row("c", fix1, "docs/x.md", date="2026-02-01T00:00:00Z"), "minus_text": ["stale"]},
        ]
        # at base all three wrong lines coexist; at fix1 only two do
        sha, present, tried = best_snapshot(repo_path, rows, reader="r1")
        assert sha == base and present == 3
        assert tried == {base: 3, fix1: 2}

    def test_missing_doc_at_snapshot_is_skipped(self, repo):
        from bench.run import snapshot_plan
        repo_path, base, fix1, fix2 = repo
        rows = [{**_row("z", fix1, "docs/gone.md", date="x"), "minus_text": ["anything"]}]
        plan, selected = snapshot_plan(repo_path, fix1, rows, reader="r1")
        assert plan == [] and selected == {}


class TestIssuesFromResults:
    def test_mirrors_the_audit_issue_shape(self, temp_dir):
        result = DocAnalysisResult(
            path=Path("docs/a.md"), classification="reference", confidence=0.9,
            classification_reason="r", matched_shadows=["src/x.py"],
            findings=[DocFinding(category="stale_content", severity="error", description="says X",
                                 shadow_ref="src/x.py", evidence="does Y", remediation="fix",
                                 verdict="confirmed", confidence=0.8)],
        )
        (issue,) = issues_from_results([result])
        assert issue["path"] == "docs/a.md"
        assert issue["category"] == "doc_stale_content"
        assert issue["exclude_key"] == "doc-analysis"
        assert issue["line_start"] is None
        assert "says X" in issue["message"] and "does Y" in issue["message"]
        assert issue["verdict"] == "confirmed"

    def test_debris_result_becomes_one_debris_issue(self):
        result = DocAnalysisResult(path=Path("notes.md"), classification="process_artifact",
                                   confidence=0.9, classification_reason="scratch")
        (issue,) = issues_from_results([result])
        assert issue["category"] == "debris"


class TestRunParents:
    @pytest.fixture
    def repo(self, temp_dir):
        repo = temp_dir / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        p1 = _commit(repo, "base", {"README.md": "# A\n\nold\n", "docs/x.md": "# X\n\nold\n"})
        _commit(repo, "fix", {"README.md": "# A\n\nnew\n"})
        return repo, p1

    def test_checks_out_parent_and_analyses_only_touched_docs(self, repo, temp_dir):
        repo_path, p1 = repo
        out = temp_dir / "runs" / "t1"
        seen = {}

        def fake_shadow(workdir: Path) -> dict:
            seen["shadow_at"] = _git(workdir, "rev-parse", "HEAD")
            return {"seconds": 0.1}

        def fake_analyze(workdir: Path, docs: list[str]) -> list[DocAnalysisResult]:
            seen["docs"] = docs
            seen["readme_at_parent"] = (workdir / "README.md").read_text(encoding="utf-8")
            return [DocAnalysisResult(path=Path("README.md"), classification="reference", confidence=1.0,
                                      classification_reason="r",
                                      findings=[DocFinding(category="stale_content", severity="error",
                                                           description="says `old`", shadow_ref="", evidence="",
                                                           remediation="")])]

        plan = [{"parent": p1, "docs": ["README.md"], "rows": 1}]
        summary = run_parents(repo_path, plan, out, shadow=fake_shadow, analyze=fake_analyze)

        assert seen["shadow_at"] == p1
        assert seen["docs"] == ["README.md"]
        assert "old" in seen["readme_at_parent"]
        written = json.loads((out / f"{p1}.json").read_text(encoding="utf-8"))
        assert written["issues"][0]["message"].startswith("says `old`")
        assert written["meta"]["docs"] == ["README.md"]
        assert summary["parents_run"] == 1
        # the tree is restored afterwards
        assert (repo_path / "README.md").read_text(encoding="utf-8") == "# A\n\nnew\n"

    def test_skips_parents_already_run(self, repo, temp_dir):
        repo_path, p1 = repo
        out = temp_dir / "runs" / "t1"
        out.mkdir(parents=True)
        (out / f"{p1}.json").write_text('{"issues": [], "meta": {}}', encoding="utf-8")
        calls = []
        summary = run_parents(repo_path, [{"parent": p1, "docs": ["README.md"], "rows": 1}], out,
                              shadow=lambda w: calls.append("s") or {}, analyze=lambda w, d: calls.append("a") or [])
        assert calls == [] and summary["parents_skipped"] == 1

    def test_failure_is_recorded_and_the_batch_continues(self, repo, temp_dir):
        repo_path, p1 = repo
        out = temp_dir / "runs" / "t1"

        def bad_analyze(workdir, docs):
            raise RuntimeError("boom")

        summary = run_parents(repo_path, [{"parent": p1, "docs": ["README.md"], "rows": 1}], out,
                              shadow=lambda w: {}, analyze=bad_analyze)
        assert summary["parents_failed"] == 1
        assert not (out / f"{p1}.json").exists()
        assert (out / f"{p1}.error.txt").exists()
