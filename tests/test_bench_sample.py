"""Tests for the reader spot-check sampler (bench Phase 0.4, wiki specs/0005)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from bench.sample import render_checklist, sample_rows  # noqa: E402


def _rows(repo, n, partition="correction"):
    return [{
        "row_id": f"{repo}:c:{i}", "repo": repo, "path": "README.md", "old_start": i, "old_len": 1,
        "minus_text": [f"old {i}"], "plus_text": [f"new {i}"],
        "labels": {"r1": {"partition": partition, "domain": "checkout", "kind": "false_statement",
                          "claim_shape": "behaviour", "claim": f"claim {i}", "confidence": 0.8}},
    } for i in range(n)]


def test_sample_is_deterministic_and_stratified_by_repo():
    rows = _rows("a", 90) + _rows("b", 10)
    s1 = sample_rows(rows, n=20, seed=35, reader="r1")
    s2 = sample_rows(rows, n=20, seed=35, reader="r1")
    assert [r["row_id"] for r in s1] == [r["row_id"] for r in s2]
    assert len(s1) == 20
    by_repo = {}
    for r in s1:
        by_repo[r["repo"]] = by_repo.get(r["repo"], 0) + 1
    assert by_repo["a"] == 18 and by_repo["b"] == 2  # proportional, at least one each


def test_unlabeled_rows_are_never_sampled():
    rows = _rows("a", 5)
    rows[0]["labels"] = None
    assert all(r["labels"] for r in sample_rows(rows, n=5, seed=1, reader="r1"))


def test_checklist_has_one_line_per_row_and_an_empty_owner_column():
    rows = sample_rows(_rows("a", 3), n=3, seed=1, reader="r1")
    md = render_checklist(rows, reader="r1")
    assert md.count("| a:c:") == 3
    assert "| owner |" in md.splitlines()[0]
    assert "claim 0" in md
