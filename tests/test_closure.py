"""Tests for the zero-LLM closure diff (``osoji verify``)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from osoji.cli import main
from osoji.closure import (
    SCHEMA,
    ClosureDiff,
    compute_closure,
    closure_to_dict,
    load_issues,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _issue(
    path,
    category,
    message,
    *,
    severity="warning",
    finding_id=None,
    verdict=None,
):
    """Build a serialized-audit issue dict (mirrors format_audit_json)."""
    d = {
        "path": path,
        "severity": severity,
        "category": category,
        "message": message,
        "remediation": "fix it",
    }
    if finding_id is not None:
        d["finding_id"] = finding_id
    if verdict is not None:
        d["verdict"] = verdict
    return d


def _write_result(root: Path, issues, *, name="analysis/audit-result.json"):
    """Write an audit-result.json under .osoji/<name> and return its path."""
    out = root / ".osoji" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"passed": True, "issues": issues}, indent=2),
        encoding="utf-8",
    )
    return out


# ---------------------------------------------------------------------------
# compute_closure — bucket assignment
# ---------------------------------------------------------------------------


def test_all_four_buckets():
    baseline = [
        _issue("a.py", "debris", "L1-2: closed one", finding_id="ID_CLOSED"),
        _issue("b.py", "debris", "L3-4: still here", finding_id="ID_OPEN"),
        _issue("c.py", "obligation_violation", "dismissed one", finding_id="ID_DIS"),
    ]
    current = [
        _issue("b.py", "debris", "L9-9: still here", finding_id="ID_OPEN"),
        _issue(
            "c.py",
            "obligation_violation",
            "dismissed one",
            finding_id="ID_DIS",
            verdict="dismissed",
        ),
        _issue("d.py", "debris", "L1-1: brand new", finding_id="ID_NEW"),
    ]

    diff = compute_closure(baseline, current)

    assert [r.finding_id for r in diff.closed] == ["ID_CLOSED"]
    assert [r.finding_id for r in diff.closed_by_dismissal] == ["ID_DIS"]
    assert [r.finding_id for r in diff.still_open] == ["ID_OPEN"]
    assert [r.finding_id for r in diff.new] == ["ID_NEW"]


def test_finding_id_join_preferred_over_composite():
    # Same id on both sides, but the message-core (and thus composite key)
    # differs. The join must follow the id -> still_open, not (closed + new).
    baseline = [
        _issue("a.py", "debris", "L1-2: old wording", finding_id="STABLE"),
    ]
    current = [
        _issue(
            "a.py", "debris", "L40-41: entirely different wording",
            severity="info", finding_id="STABLE",
        ),
    ]

    diff = compute_closure(baseline, current)

    assert not diff.closed
    assert not diff.new
    assert [r.finding_id for r in diff.still_open] == ["STABLE"]
    # the surviving record reflects the current state (re-graded severity)
    assert diff.still_open[0].severity == "info"


def test_composite_join_survives_line_number_drift():
    # A symbol-less finding folds line numbers into its id, so an insert above
    # gives it a *different* id across runs. The composite fallback strips the
    # line marker from the message-core and must still recognise it as the same
    # finding -> still_open, not (closed + new).
    baseline = [
        _issue("a.py", "junk_deadcode", "L10: function `foo` — never called",
               finding_id="HASH_LINE_10"),
    ]
    current = [
        _issue("a.py", "junk_deadcode", "L57: function `foo` — never called",
               finding_id="HASH_LINE_57"),
    ]

    diff = compute_closure(baseline, current)

    assert not diff.closed
    assert not diff.new
    assert len(diff.still_open) == 1


def test_composite_join_when_finding_id_absent():
    baseline = [_issue("a.py", "debris", "L1-2: no id here")]
    current = [_issue("a.py", "debris", "L88-90: no id here")]

    diff = compute_closure(baseline, current)

    assert not diff.closed
    assert not diff.new
    assert len(diff.still_open) == 1
    # unmatched-with-no-id would report a composite join key
    assert "no id here" in diff.still_open[0].join_key


def test_dismissed_current_finding_is_closed_by_dismissal_not_open():
    baseline = [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]
    current = [
        _issue("a.py", "debris", "L1-2: thing", finding_id="X", verdict="dismissed"),
    ]

    diff = compute_closure(baseline, current)

    assert not diff.still_open
    assert [r.finding_id for r in diff.closed_by_dismissal] == ["X"]


def test_exit_code_one_while_still_open():
    baseline = [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]
    current = [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]
    assert compute_closure(baseline, current).exit_code == 1


def test_exit_code_zero_when_nothing_still_open():
    baseline = [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]
    current = []  # all closed
    assert compute_closure(baseline, current).exit_code == 0

    # new findings alone do not force a nonzero exit
    diff = compute_closure([], [_issue("a.py", "debris", "L1: new", finding_id="N")])
    assert diff.exit_code == 0


# ---------------------------------------------------------------------------
# JSON serialization shape
# ---------------------------------------------------------------------------


def test_closure_to_dict_schema_shape():
    baseline = [_issue("a.py", "debris", "L1-2: gone", finding_id="G")]
    current = [_issue("b.py", "debris", "L1-2: fresh", finding_id="F")]
    payload = closure_to_dict(compute_closure(baseline, current))

    assert payload["schema"] == SCHEMA == "closure-diff/1"
    for bucket in ("closed", "closed_by_dismissal", "still_open", "new"):
        assert bucket in payload
        assert isinstance(payload[bucket], list)

    rec = payload["closed"][0]
    assert set(rec) >= {"path", "category", "severity", "finding_id", "join_key"}
    assert rec["path"] == "a.py"
    assert rec["finding_id"] == "G"


# ---------------------------------------------------------------------------
# CLI: osoji verify
# ---------------------------------------------------------------------------


def test_verify_missing_baseline_errors(tmp_path):
    runner = CliRunner()
    _write_result(tmp_path, [])  # current exists, no baseline
    result = runner.invoke(main, ["verify", str(tmp_path)])
    assert result.exit_code != 0
    assert "baseline" in result.output.lower()


def test_verify_snapshot_writes_outside_analysis(tmp_path):
    runner = CliRunner()
    current = _write_result(
        tmp_path, [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]
    )
    result = runner.invoke(main, ["verify", str(tmp_path), "--snapshot"])
    assert result.exit_code == 0

    baseline = tmp_path / ".osoji" / "audit-baseline.json"
    assert baseline.exists()
    # deliberately OUTSIDE the analysis/ dir the audit wipes each run
    analysis_root = tmp_path / ".osoji" / "analysis"
    assert analysis_root not in baseline.parents
    # byte-for-byte copy of the current result
    assert baseline.read_bytes() == current.read_bytes()


def test_verify_snapshot_without_current_errors(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["verify", str(tmp_path), "--snapshot"])
    assert result.exit_code != 0


def test_verify_json_output_and_exit_code(tmp_path):
    runner = CliRunner()
    # baseline: one finding; current: still open -> exit 1
    _write_result(
        tmp_path,
        [_issue("a.py", "debris", "L1-2: thing", finding_id="X")],
        name="audit-baseline.json",
    )
    _write_result(
        tmp_path, [_issue("a.py", "debris", "L9-9: thing", finding_id="X")]
    )
    result = runner.invoke(main, ["verify", str(tmp_path), "--format", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema"] == "closure-diff/1"
    assert [r["finding_id"] for r in payload["still_open"]] == ["X"]


def test_verify_text_all_closed_exits_zero(tmp_path):
    runner = CliRunner()
    _write_result(
        tmp_path,
        [_issue("a.py", "debris", "L1-2: thing", finding_id="X")],
        name="audit-baseline.json",
    )
    _write_result(tmp_path, [])  # everything closed
    result = runner.invoke(main, ["verify", str(tmp_path)])
    assert result.exit_code == 0
    assert "closed" in result.output.lower()


def test_verify_baseline_override_flag(tmp_path):
    runner = CliRunner()
    custom = tmp_path / "my-baseline.json"
    custom.write_text(
        json.dumps(
            {"issues": [_issue("a.py", "debris", "L1-2: thing", finding_id="X")]}
        ),
        encoding="utf-8",
    )
    _write_result(tmp_path, [])  # current: all closed
    result = runner.invoke(
        main, ["verify", str(tmp_path), "--baseline", str(custom)]
    )
    assert result.exit_code == 0


def test_load_issues_reads_issues_array(tmp_path):
    path = _write_result(tmp_path, [_issue("a.py", "debris", "L1: x", finding_id="X")])
    issues = load_issues(path)
    assert [i["finding_id"] for i in issues] == ["X"]
