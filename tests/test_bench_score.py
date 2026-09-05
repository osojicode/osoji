"""Tests for the benchmark scorer (bench Phase 0, wiki specs/0005).

Given labeled rows (the docs-fix ground truth at a parent commit) and the
findings osoji produced at that parent, the scorer decides which rows were
hit and reports recall overall, by kind and by claim shape. Only rows
labeled correction/deletion in the checkout domain count. Findings that hit
no row are the precision candidates a reader panel adjudicates later.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from bench.score import counting_rows, label_of, match_findings, score  # noqa: E402


def _row(n, *, path="README.md", start=10, length=2, minus=("Run `npm run build`.",),
         partition="correction", domain="checkout", kind="wrong_command", shape="script",
         reader="r1", parent="p1"):
    return {
        "row_id": f"x:{parent}:{n}", "repo": "x", "commit": "c" * 40, "parent": parent,
        "path": path, "old_start": start, "old_len": length, "minus_text": list(minus),
        "plus_text": ["fixed"], "labels": {
            reader: {"partition": partition, "domain": domain, "kind": kind,
                     "claim_shape": shape, "claim": "c", "confidence": 0.8},
        },
    }


def _finding(path="README.md", line_start=10, line_end=None, message="says X", category="doc_stale_content"):
    return {"path": path, "line_start": line_start, "line_end": line_end, "message": message,
            "category": category, "severity": "error", "exclude_key": "doc-analysis"}


class TestLabelOf:
    def test_named_reader(self):
        row = _row(1)
        assert label_of(row, "r1")["kind"] == "wrong_command"

    def test_missing_reader_is_none(self):
        assert label_of(_row(1), "r9") is None

    def test_default_reader_is_the_only_one(self):
        assert label_of(_row(1), None)["kind"] == "wrong_command"


class TestCountingRows:
    def test_only_checkout_corrections_and_deletions_count(self):
        rows = [
            _row(1), _row(2, partition="deletion"), _row(3, partition="addition"),
            _row(4, partition="restructure"), _row(5, domain="world"), _row(6, domain="runtime"),
        ]
        assert [r["row_id"] for r in counting_rows(rows, "r1")] == ["x:p1:1", "x:p1:2"]

    def test_unlabeled_rows_never_count(self):
        row = _row(1)
        row["labels"] = None
        assert counting_rows([row], "r1") == []


class TestMatchFindings:
    def test_line_overlap_within_window(self):
        row = _row(1, start=10, length=2)
        assert match_findings(row, [_finding(line_start=14)], window=3)
        assert not match_findings(row, [_finding(line_start=15)], window=3)

    def test_line_range_finding(self):
        row = _row(1, start=10, length=2)
        assert match_findings(row, [_finding(line_start=1, line_end=9)], window=0) == []
        assert match_findings(row, [_finding(line_start=1, line_end=10)], window=0)

    def test_phrase_overlap_hits_without_lines(self):
        row = _row(1, minus=("Run `npm run build` to compile.",))
        f = _finding(line_start=None, message="The doc says `npm run build` but the script is `pnpm build`.")
        assert match_findings(row, [f], window=0)

    def test_other_path_never_matches(self):
        assert match_findings(_row(1), [_finding(path="docs/other.md", line_start=10)], window=5) == []

    def test_path_normalisation(self):
        assert match_findings(_row(1, path="docs/a.md"), [_finding(path="docs\\a.md", line_start=10)], window=0)


class TestScore:
    def test_recall_by_kind_and_shape(self):
        rows = [
            _row(1, kind="wrong_command", shape="script", start=10),
            _row(2, kind="wrong_path", shape="path", start=50),
            _row(3, kind="false_statement", shape="behaviour", start=90),
            _row(4, partition="addition"),  # never counts
        ]
        findings = {"p1": [_finding(line_start=11), _finding(line_start=300, message="unrelated")]}

        result = score(rows, findings, reader="r1", window=3)

        assert result["rows"] == 3 and result["hits"] == 1
        assert result["recall"] == 1 / 3
        assert result["by_kind"]["wrong_command"] == {"rows": 1, "hits": 1}
        assert result["by_kind"]["wrong_path"] == {"rows": 1, "hits": 0}
        assert result["by_shape"]["script"] == {"rows": 1, "hits": 1}
        assert result["findings_total"] == 2
        assert result["findings_unmatched"] == 1  # precision candidate
        assert result["rows_detail"][0]["hit"] is True
        assert result["rows_detail"][1]["hit"] is False

    def test_parent_without_findings_counts_as_all_misses(self):
        rows = [_row(1, parent="p1"), _row(2, parent="p2")]
        result = score(rows, {"p1": [_finding(line_start=10)]}, reader="r1", window=0)
        assert (result["rows"], result["hits"]) == (2, 1)
        assert result["parents_run"] == 1 and result["parents_total"] == 2

    def test_only_parents_with_a_run_when_requested(self):
        rows = [_row(1, parent="p1"), _row(2, parent="p2")]
        result = score(rows, {"p1": [_finding(line_start=10)]}, reader="r1", window=0, run_parents_only=True)
        assert (result["rows"], result["hits"]) == (1, 1)
