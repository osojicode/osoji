"""Tests for scripts/corpus_replay.py — the thin CLI shell over eval_lib.

Only argument parsing, case-selection wiring, and exit-code behavior are
exercised here (everything else lives in eval_lib and is covered by
test_eval_lib.py). ``--gate-check`` is fully covered end-to-end: it never
constructs a provider or makes an LLM call, so it needs no API key and no
fake-provider plumbing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import corpus_replay  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic corpus builder (case.json/finding.json/expected.json only —
# --gate-check and case-selection never touch source/).
# ---------------------------------------------------------------------------


def _write_case(
    corpus_root: Path,
    category: str,
    dirname: str,
    *,
    verdict: str = "confirmed",
    gray: bool = False,
    accepted: bool = True,
) -> str:
    case_dir = corpus_root / category / dirname
    case_dir.mkdir(parents=True, exist_ok=True)

    case_data = {
        "schema": "corpus-case/1",
        "slug": dirname,
        "category": category,
        "detector": "deadcode",
        "gap_type": "reachability",
        "language": "python",
        "origin": {
            "repo": "example/repo",
            "remote": "https://example.com/example/repo.git",
            "commit": "abc123",
            "swept_at": "2026-07-21T00:00:00Z",
            "osoji_version": "0.0.0-test",
            "sweep_run": "test-run",
        },
        "snapshot_ref": None,
        "evidence_policy": "frozen",
    }
    (case_dir / "case.json").write_text(json.dumps(case_data), encoding="utf-8")

    finding_data = {
        "detector": "deadcode:dead_code",
        "gap_type": "reachability",
        "path": "src/app/util.py",
        "line_start": 10,
        "line_end": 12,
        "symbol": "unused_helper",
        "contract_source": "declared",
        "contract_claim": "unused_helper is defined at module scope",
        "observed_behavior": "no references found",
        "evidence": [],
        "id": "",
        "verdict": None,
        "confidence": None,
        "triage_reasoning": None,
        "suggested_fix": None,
        "severity": None,
        "contract_class": None,
        "evidence_fingerprint": None,
    }
    (case_dir / "finding.json").write_text(json.dumps(finding_data), encoding="utf-8")

    expected_data = {
        "schema": "corpus-expected/1",
        "verdict": verdict,
        "reasoning": "adjudicator's reasoning",
        "gray": gray,
        "gray_reason": None,
        "expected_contract_class": None,
        "adjudicated_by": "jf",
        "adjudicated_at": "2026-07-21T00:00:00Z",
        "accepted": accepted,
    }
    (case_dir / "expected.json").write_text(json.dumps(expected_data), encoding="utf-8")

    return f"{category}/{dirname}"


def _write_splits(corpus_root: Path, assignments: dict[str, str]) -> None:
    data = {
        "schema": "corpus-splits/1",
        "seed": 1,
        "ratios": {"train": 0.5, "val": 0.25, "holdout": 0.25},
        "assignments": assignments,
    }
    (corpus_root / "splits.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# --gate-check
# ---------------------------------------------------------------------------


def test_gate_check_passes_on_fully_covered_corpus(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--gate-check"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASSED" in out


def test_gate_check_fails_when_corpus_too_small(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(5)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--gate-check"])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def test_gate_check_requires_no_api_key(tmp_path, monkeypatch, capsys):
    """--gate-check must work with no API key present: never constructs a provider."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OSOJI_TOKEN", raising=False)
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--gate-check"])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Argument / selection validation
# ---------------------------------------------------------------------------


def test_empty_case_selection_exits_nonzero(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir(parents=True)

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--gate-check"])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "empty case selection" in err


def test_bad_variant_spec_exits_nonzero(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--variant", "bare_name_no_equals", "--gate-check"]
    )

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "error" in err.lower()


def test_unknown_split_choice_raises_systemexit(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")

    # "bogus" is not one of argparse's --split choices (train|val|holdout).
    with pytest.raises(SystemExit):
        corpus_replay.main(["--corpus", str(corpus_root), "--split", "bogus", "--gate-check"])


def test_split_absent_from_splits_ratios_exits_nonzero(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", "case_0")]
    # splits.json only defines train/val — holdout is a valid --split choice
    # but absent from this file's own ratios.
    data = {
        "schema": "corpus-splits/1",
        "seed": 1,
        "ratios": {"train": 0.5, "val": 0.5},
        "assignments": {k: "train" for k in keys},
    }
    (corpus_root / "splits.json").write_text(json.dumps(data), encoding="utf-8")

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--split", "holdout"])

    assert exit_code != 0


def test_missing_splits_file_for_split_exits_nonzero(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")
    # No splits.json written at all.

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--split", "train"])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "error" in err.lower()


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------


def test_parse_variants_defaults_to_baseline_default():
    variants = corpus_replay._parse_variants(None)

    assert len(variants) == 1
    assert variants[0].name == "baseline"
    assert variants[0].prompt_source == "@default"


def test_parse_variants_rejects_duplicate_names():
    with pytest.raises(ValueError, match="duplicate"):
        corpus_replay._parse_variants(["a=@default", "a=@omit:closing"])


def test_parse_only_splits_on_comma():
    assert corpus_replay._parse_only("a,b, c") == ("a", "b", "c")
    assert corpus_replay._parse_only(None) == ()
    assert corpus_replay._parse_only("") == ()
