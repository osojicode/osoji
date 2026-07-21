"""Tests for scripts/corpus_replay.py — the thin CLI shell over eval_lib.

Only argument parsing, case-selection wiring, and exit-code behavior are
exercised here (everything else lives in eval_lib and is covered by
test_eval_lib.py). ``--gate-check`` is fully covered end-to-end: it never
constructs a provider or makes an LLM call, so it needs no API key and no
fake-provider plumbing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import corpus_replay  # noqa: E402
import eval_lib  # noqa: E402


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
    evidence_policy: str = "frozen",
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
        "evidence_policy": evidence_policy,
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
# Canned evaluate_corpus fake (review Important 4) — monkeypatches
# corpus_replay's own imported name, not eval_lib's, since Python resolves
# `evaluate_corpus(...)` against the caller module's namespace.
# ---------------------------------------------------------------------------


def _canned_record(**overrides) -> dict:
    base = {
        "schema": "osoji-verdict/1", "record": "verdict", "run_id": "eval-test",
        "variant": "baseline", "repeat": 0, "source": "corpus", "case": "dead_code/case_0",
        "finding_id": "f1", "detector": "deadcode:dead_code", "category": "dead_code",
        "gap_type": "reachability", "path": "src/app/util.py", "symbol": "unused_helper",
        "line_start": 10, "line_end": 12, "expected_verdict": "confirmed", "gray": False,
        "verdict": "confirmed", "confidence": 0.9, "severity": "warning", "contract_class": None,
        "triage_reasoning": "because", "suggested_fix": "remove it",
        "insufficient_evidence": False, "evidence_policy": "frozen", "correct": True,
    }
    base.update(overrides)
    return base


def _canned_run_meta(**overrides) -> dict:
    base = {
        "schema": "osoji-verdict/1", "record": "run_meta", "run_id": "eval-test",
        "started_at": "2026-07-21T00:00:00+00:00", "finished_at": "2026-07-21T00:00:01+00:00",
        "duration_s": 1.0,
        "variants": {"baseline": {"prompt_sha256": "abc123", "prompt_source": "@default"}},
        "provider": "anthropic", "model": "test-model", "osoji_commit": "deadbeef",
        "claim_builder_schema_version": "cb-3",
        "corpus": {"root": None, "n_cases": 1, "n_gray": 0, "split": None, "only": None,
                   "exclude_gray": False},
        "repeats": 1, "repeat_offset": 0, "batch_size": 12,
        "tokens": {"input": 100, "output": 40}, "metrics": {},
    }
    base.update(overrides)
    return base


def _make_fake_evaluate_corpus(calls: list):
    """An async stand-in for eval_lib.evaluate_corpus that records its kwargs
    and returns a canned EvalRun — no staging, no provider, no LLM call."""

    async def _fake(cases, variants, **kwargs):
        calls.append(kwargs)
        run_id = kwargs.get("run_id")
        record = _canned_record(run_id=run_id, variant=variants[0].name, case=cases[0].key)
        run_meta = _canned_run_meta(run_id=run_id)
        return eval_lib.EvalRun(records=[record], run_meta=run_meta)

    return _fake


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


def test_gate_check_plain_still_works(tmp_path, capsys):
    """No filter flags: proves the rejections below are scoped to the filter
    combination, not to --gate-check itself (review Important 1)."""
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--gate-check"])

    assert exit_code == 0
    assert "PASSED" in capsys.readouterr().out


def test_gate_check_rejects_split_flag(tmp_path, capsys):
    """A filtered case list compared against the WHOLE splits.json would read
    every unselected case as a stale assignment (false FAILED) — reject the
    combination outright instead (review Important 1)."""
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--gate-check", "--split", "train"]
    )

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "--gate-check" in err
    assert "--split" in err


def test_gate_check_rejects_only_flag(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--gate-check", "--only", keys[0]]
    )

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "--only" in err


def test_gate_check_rejects_exclude_gray_flag(tmp_path, capsys):
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", f"case_{i}") for i in range(90)]
    _write_splits(corpus_root, {k: "train" for k in keys})

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--gate-check", "--exclude-gray"]
    )

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "--exclude-gray" in err


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


def test_split_rejected_under_bootstrap_source(tmp_path, capsys):
    """splits.json only ever assigns corpus-source keys — --split with
    --source bootstrap must be rejected, not silently ignored (review
    Minor 2)."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"commit": "abc", "entries": []}), encoding="utf-8")

    exit_code = corpus_replay.main(
        ["--source", "bootstrap", "--bootstrap", str(manifest_path), "--split", "train"]
    )

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "--split" in err
    assert "bootstrap" in err


def test_split_still_allowed_under_source_both(tmp_path, monkeypatch):
    """--split + --source both is a legitimate combination (only the corpus
    subset gets filtered) — must not be rejected by the Minor-2 bootstrap
    check. Uses the canned evaluate_corpus fake (no --gate-check here: that
    combination is separately rejected by Important 1, tested above)."""
    corpus_root = tmp_path / "corpus"
    keys = [_write_case(corpus_root, "dead_code", "case_0")]
    _write_splits(corpus_root, {k: "train" for k in keys})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"commit": "abc", "entries": []}), encoding="utf-8")
    calls: list = []
    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _make_fake_evaluate_corpus(calls))

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--source", "both", "--bootstrap", str(manifest_path),
         "--split", "train", "--out", str(tmp_path / "out.ndjson")]
    )

    assert exit_code == 0
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Primary replay path (review Important 2 + Important 4): evaluate_corpus is
# monkeypatched with a canned async fake — no staging, no provider, no LLM.
# ---------------------------------------------------------------------------


def test_main_replay_writes_ndjson_to_out_path(tmp_path, monkeypatch):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")
    calls: list = []
    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _make_fake_evaluate_corpus(calls))
    out_path = tmp_path / "out.ndjson"

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--out", str(out_path)])

    assert exit_code == 0
    assert len(calls) == 1
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["record"] == "verdict"
    assert json.loads(lines[1])["record"] == "run_meta"


def test_main_replay_applies_default_run_id_pattern(tmp_path, monkeypatch):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")
    calls: list = []
    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _make_fake_evaluate_corpus(calls))

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--out", str(tmp_path / "out.ndjson")]
    )

    assert exit_code == 0
    assert re.match(r"^eval-\d{8}-[0-9a-f]{8}$", calls[0]["run_id"])


def test_main_replay_uses_explicit_run_id_when_given(tmp_path, monkeypatch):
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")
    calls: list = []
    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _make_fake_evaluate_corpus(calls))

    exit_code = corpus_replay.main(
        ["--corpus", str(corpus_root), "--out", str(tmp_path / "out.ndjson"),
         "--run-id", "custom-run-id"]
    )

    assert exit_code == 0
    assert calls[0]["run_id"] == "custom-run-id"


def test_main_replay_stdout_bytes_are_lf_clean(tmp_path, monkeypatch, capfdbinary):
    """--out - must be byte-identical to file output: no CRLF translation
    from a real (text-mode, universal-newlines) stdout stream (review
    Important 2)."""
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")
    calls: list = []
    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _make_fake_evaluate_corpus(calls))

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--out", "-"])

    assert exit_code == 0
    out_bytes = capfdbinary.readouterr().out
    assert b"\r" not in out_bytes
    lines = out_bytes.decode("utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["record"] == "verdict"
    assert json.loads(lines[1])["record"] == "run_meta"


def test_main_replay_propagates_valueerror_cleanly(tmp_path, monkeypatch, capsys):
    """evaluate_corpus raising an expected ValueError must produce a clean
    one-line stderr message and a nonzero exit — no raw traceback (review
    Important 3's CLI-side ask)."""
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_0")

    async def _raising(cases, variants, **kwargs):
        raise ValueError("synthetic staging failure for case_0")

    monkeypatch.setattr(corpus_replay, "evaluate_corpus", _raising)

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--out", "-"])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "synthetic staging failure" in err
    assert "Traceback" not in err


def test_main_replay_staging_failure_exits_cleanly_no_provider_needed(
    tmp_path, monkeypatch, capsys
):
    """A real (unmocked) rebuild-policy case with no source/ must fail
    staging — and since evaluate_corpus now stages BEFORE constructing a
    provider (review Important 3), this needs no API key and never reaches
    the network, proven end-to-end through the CLI."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OSOJI_TOKEN", raising=False)
    corpus_root = tmp_path / "corpus"
    _write_case(corpus_root, "dead_code", "case_bad", evidence_policy="rebuild")
    # No source/ directory is ever written by _write_case.

    exit_code = corpus_replay.main(["--corpus", str(corpus_root), "--out", "-"])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "case_bad" in err
    assert "Traceback" not in err


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
