"""Tests for scripts/eval_lib.py — the V1-7 corpus evaluator library core.

Builds synthetic corpus-case/1 trees under ``tmp_path`` (never touching the
real ``tests/fixtures/prompt_regression`` corpus, which has no cases yet) and
exercises the loader, snapshot staging, claim construction, metrics, and the
``osoji-verdict/1`` NDJSON reader/writer. Fully deterministic — no LLM calls,
no network.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import eval_lib  # noqa: E402
from eval_lib import (  # noqa: E402
    CorpusCase,
    GateReport,
    Variant,
    build_case_claim,
    cases_from_bootstrap_manifest,
    check_gepa_gate,
    compute_metrics,
    evaluate_corpus,
    load_corpus,
    load_splits,
    read_verdict_ndjson,
    resolve_variant,
    select_cases,
    stage_case,
    suggest_split,
    write_verdict_ndjson,
)
from osoji.config import Config  # noqa: E402
from osoji.findings import Finding  # noqa: E402
from osoji.llm.types import CompletionResult, ToolCall  # noqa: E402
from osoji.triage import TRIAGE_SYSTEM_PROMPT  # noqa: E402


# ---------------------------------------------------------------------------
# Fake provider (adapted from tests/test_triage.py:43-70)
# ---------------------------------------------------------------------------


class FakeProvider:
    """Minimal async provider returning queued CompletionResults in order."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []
        self.closed = False

    async def complete(self, messages, system, options):
        self.calls.append({"messages": messages, "system": system, "options": options})
        return self._results.pop(0)

    async def close(self):
        self.closed = True


def verdicts_result(verdicts, *, in_tok=100, out_tok=40) -> CompletionResult:
    """A claim-mode batch result: one submit_triage_verdicts tool call."""
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(id="tc1", name="submit_triage_verdicts", input={"verdicts": verdicts})],
        input_tokens=in_tok,
        output_tokens=out_tok,
        model="test",
        stop_reason="tool_use",
    )


# ---------------------------------------------------------------------------
# Synthetic corpus builders
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _finding_dict(**overrides) -> dict:
    base = {
        "detector": "deadcode:dead_code",
        "gap_type": "reachability",
        "path": "src/app/util.py",
        "line_start": 10,
        "line_end": 12,
        "symbol": "unused_helper",
        "contract_source": "declared",
        "contract_claim": "unused_helper is defined at module scope",
        "observed_behavior": "no references found in the scanned corpus",
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
    base.update(overrides)
    return base


def _case_json(
    category: str,
    dirname: str,
    *,
    snapshot_ref: str | None = None,
    evidence_policy: str = "rebuild",
) -> dict:
    return {
        "schema": "corpus-case/1",
        "slug": dirname,
        "category": category,
        "detector": "deadcode",
        "gap_type": "reachability",
        "language": "python",
        "origin": {
            "repo": "example/repo",
            "remote": "https://example.com/example/repo.git",
            "commit": "abc123def456",
            "swept_at": "2026-07-21T00:00:00Z",
            "osoji_version": "0.0.0-test",
            "sweep_run": "test-run-1",
        },
        "snapshot_ref": snapshot_ref,
        "evidence_policy": evidence_policy,
    }


def _expected_json(
    *,
    verdict: str = "confirmed",
    gray: bool = False,
    accepted: bool = True,
    overrides: dict | None = None,
) -> dict:
    data = {
        "schema": "corpus-expected/1",
        "verdict": verdict,
        "reasoning": "adjudicator's reasoning goes here",
        "gray": gray,
        "gray_reason": None,
        "expected_contract_class": None,
        "adjudicated_by": "jf",
        "adjudicated_at": "2026-07-21T00:00:00Z",
        "accepted": accepted,
    }
    if overrides:
        data.update(overrides)
    return data


def make_case(
    corpus_root: Path,
    category: str,
    dirname: str,
    *,
    finding_overrides: dict | None = None,
    case_overrides: dict | None = None,
    expected_overrides: dict | None = None,
    snapshot_ref: str | None = None,
    evidence_policy: str = "rebuild",
    verdict: str = "confirmed",
    gray: bool = False,
    accepted: bool = True,
    source_files: dict[str, str] | None = None,
    write_source: bool = True,
) -> str:
    """Write one corpus-case/1 directory; returns its key."""

    case_dir = corpus_root / category / dirname
    case_data = _case_json(
        category, dirname, snapshot_ref=snapshot_ref, evidence_policy=evidence_policy
    )
    if case_overrides:
        case_data.update(case_overrides)
    _write_json(case_dir / "case.json", case_data)

    finding = _finding_dict(**(finding_overrides or {}))
    _write_json(case_dir / "finding.json", finding)

    expected = _expected_json(
        verdict=verdict, gray=gray, accepted=accepted, overrides=expected_overrides
    )
    _write_json(case_dir / "expected.json", expected)

    if write_source and snapshot_ref is None:
        files = source_files or {"src/app/util.py": "def unused_helper():\n    pass\n"}
        for rel, content in files.items():
            p = case_dir / "source" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

    return f"{category}/{dirname}"


# ---------------------------------------------------------------------------
# load_corpus
# ---------------------------------------------------------------------------


def test_load_corpus_valid_case_loads_all_fields(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_basic")

    cases = load_corpus(tmp_path)

    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, CorpusCase)
    assert case.key == "dead_code/case_101_basic"
    assert case.category == "dead_code"
    assert case.case_dir == tmp_path / "dead_code" / "case_101_basic"
    assert isinstance(case.finding, Finding)
    assert case.finding.symbol == "unused_helper"
    assert case.expected_verdict == "confirmed"
    assert case.expected_reasoning == "adjudicator's reasoning goes here"
    assert case.gray is False
    assert case.evidence_policy == "rebuild"
    assert case.snapshot_root == case.case_dir
    assert case.origin["repo"] == "example/repo"
    assert case.source == "corpus"


def test_load_corpus_skips_holding_directory(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_basic")
    # A holding entry glob-matches "<category>/case_*/case.json" from corpus
    # root and must never load — it hasn't been reviewed.
    make_case(tmp_path, "_holding", "case_999_pending")

    cases = load_corpus(tmp_path)

    assert [c.key for c in cases] == ["dead_code/case_101_basic"]


def test_load_corpus_skips_unaccepted_with_warning(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_basic", accepted=True)
    make_case(tmp_path, "dead_code", "case_102_unreviewed", accepted=False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cases = load_corpus(tmp_path)

    assert [c.key for c in cases] == ["dead_code/case_101_basic"]
    assert len(caught) == 1
    assert "case_102_unreviewed" in str(caught[0].message)


def test_load_corpus_bad_case_schema_raises(tmp_path):
    key = make_case(tmp_path, "dead_code", "case_101_basic")
    case_json_path = tmp_path / "dead_code" / "case_101_basic" / "case.json"
    data = json.loads(case_json_path.read_text(encoding="utf-8"))
    data["schema"] = "corpus-case/99"
    case_json_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="case.json"):
        load_corpus(tmp_path)


def test_load_corpus_bad_expected_schema_raises(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_basic")
    expected_path = tmp_path / "dead_code" / "case_101_basic" / "expected.json"
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    data["schema"] = "corpus-expected/99"
    expected_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="expected.json"):
        load_corpus(tmp_path)


def test_load_corpus_resolves_snapshot_ref(tmp_path):
    make_case(
        tmp_path,
        "dead_code",
        "case_101_source_owner",
        source_files={"src/app/util.py": "def unused_helper():\n    pass\n"},
    )
    make_case(
        tmp_path,
        "dead_code",
        "case_102_shares_snapshot",
        snapshot_ref="dead_code/case_101_source_owner",
        finding_overrides={"symbol": "other_symbol"},
    )

    cases = {c.key: c for c in load_corpus(tmp_path)}

    owner_dir = tmp_path / "dead_code" / "case_101_source_owner"
    assert cases["dead_code/case_101_source_owner"].snapshot_root == owner_dir
    assert cases["dead_code/case_102_shares_snapshot"].snapshot_root == owner_dir
    # The dependent case's own directory carries no source/ of its own.
    assert not (tmp_path / "dead_code" / "case_102_shares_snapshot" / "source").exists()


def test_load_corpus_only_filters_by_key(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_a")
    make_case(tmp_path, "dead_code", "case_102_b")

    cases = load_corpus(tmp_path, only=["dead_code/case_102_b"])

    assert [c.key for c in cases] == ["dead_code/case_102_b"]


def test_load_corpus_exclude_gray_filters(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_a", gray=False)
    make_case(tmp_path, "dead_code", "case_102_b", gray=True)

    all_cases = load_corpus(tmp_path)
    nongray = load_corpus(tmp_path, exclude_gray=True)

    assert {c.key for c in all_cases} == {"dead_code/case_101_a", "dead_code/case_102_b"}
    assert {c.key for c in nongray} == {"dead_code/case_101_a"}


def test_load_corpus_split_filters_by_assignment(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_a")
    make_case(tmp_path, "dead_code", "case_102_b")
    splits = {
        "schema": "corpus-splits/1",
        "seed": 1,
        "ratios": {"train": 0.5, "val": 0.5},
        "assignments": {
            "dead_code/case_101_a": "train",
            "dead_code/case_102_b": "val",
        },
    }

    train_cases = load_corpus(tmp_path, split="train", splits=splits)

    assert [c.key for c in train_cases] == ["dead_code/case_101_a"]


def test_load_corpus_split_without_splits_raises(tmp_path):
    make_case(tmp_path, "dead_code", "case_101_a")

    with pytest.raises(ValueError, match="splits"):
        load_corpus(tmp_path, split="train")


def test_load_corpus_no_cases_returns_empty_list(tmp_path):
    assert load_corpus(tmp_path) == []


# ---------------------------------------------------------------------------
# stage_case
# ---------------------------------------------------------------------------


def test_stage_case_lays_out_source_and_sidecars(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root,
        "dead_code",
        "case_101_basic",
        source_files={"src/app/util.py": "def unused_helper():\n    pass\n"},
    )
    case_dir = corpus_root / "dead_code" / "case_101_basic"
    (case_dir / "symbols" / "src" / "app").mkdir(parents=True)
    (case_dir / "symbols" / "src" / "app" / "util.py.symbols.json").write_text("{}", encoding="utf-8")
    (case_dir / "facts" / "src" / "app").mkdir(parents=True)
    (case_dir / "facts" / "src" / "app" / "util.py.facts.json").write_text("{}", encoding="utf-8")
    (case_dir / "shadow").mkdir(parents=True)
    (case_dir / "shadow" / "_root.shadow.md").write_text("# root", encoding="utf-8")

    [case] = load_corpus(corpus_root)
    workdir = tmp_path / "work"
    config = stage_case(case, workdir)

    staged_root = config.root_path
    assert (staged_root / "src" / "app" / "util.py").exists()
    assert (staged_root / ".osoji" / "symbols" / "src" / "app" / "util.py.symbols.json").exists()
    assert (staged_root / ".osoji" / "facts" / "src" / "app" / "util.py.facts.json").exists()
    assert (staged_root / ".osoji" / "shadow" / "_root.shadow.md").exists()
    assert config.respect_gitignore is False


def test_stage_case_sidecars_are_optional(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_basic")

    [case] = load_corpus(corpus_root)
    config = stage_case(case, tmp_path / "work")

    assert (config.root_path / "src" / "app" / "util.py").exists()
    assert not (config.root_path / ".osoji" / "symbols").exists()


def test_stage_case_sanitizes_key_for_dirname(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_basic")

    [case] = load_corpus(corpus_root)
    workdir = tmp_path / "work"
    config = stage_case(case, workdir)

    assert config.root_path.parent == workdir
    assert "/" not in config.root_path.name
    assert "\\" not in config.root_path.name


def test_stage_case_rebuild_missing_source_raises(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root, "dead_code", "case_101_basic",
        evidence_policy="rebuild", write_source=False,
    )

    [case] = load_corpus(corpus_root)

    with pytest.raises(ValueError, match="case_101_basic"):
        stage_case(case, tmp_path / "work")


def test_stage_case_frozen_missing_source_does_not_raise(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root, "dead_code", "case_101_basic",
        evidence_policy="frozen", write_source=False,
    )

    [case] = load_corpus(corpus_root)

    config = stage_case(case, tmp_path / "work")

    # No exception, and nothing was staged (no source/ or sidecars existed to copy).
    assert config.root_path == tmp_path / "work" / "dead_code__case_101_basic"
    assert not (config.root_path / "src").exists()


# ---------------------------------------------------------------------------
# build_case_claim
# ---------------------------------------------------------------------------


def test_build_case_claim_rebuild_policy_rebuilds_evidence(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root,
        "dead_code",
        "case_101_basic",
        evidence_policy="rebuild",
        source_files={"src/app/util.py": "def unused_helper():\n    pass\n"},
        finding_overrides={
            "path": "src/app/util.py",
            "symbol": "unused_helper",
            "evidence": [],
        },
    )

    [case] = load_corpus(corpus_root)
    config = stage_case(case, tmp_path / "work")
    claim = build_case_claim(case, config)

    assert claim.finding.symbol == "unused_helper"
    # Evidence is rebuilt against the staged snapshot: even an honest-absence
    # sweep yields a cross_file_reference evidence entry, not an empty list.
    assert len(claim.finding.evidence) > 0
    assert any(e.kind == "cross_file_reference" for e in claim.finding.evidence)


def test_build_case_claim_frozen_policy_carries_evidence_through(tmp_path):
    corpus_root = tmp_path / "corpus"
    frozen_evidence = [
        {
            "kind": "cross_file_reference",
            "weight_hint": 0.5,
            "payload": {"note": "frozen from original sweep"},
        }
    ]
    make_case(
        corpus_root,
        "dead_code",
        "case_101_basic",
        evidence_policy="frozen",
        finding_overrides={"evidence": frozen_evidence},
        write_source=False,
    )

    [case] = load_corpus(corpus_root)
    config = stage_case(case, tmp_path / "work")
    claim = build_case_claim(case, config)

    assert len(claim.finding.evidence) == 1
    assert claim.finding.evidence[0].kind == "cross_file_reference"
    assert claim.finding.evidence[0].payload == {"note": "frozen from original sweep"}


def test_build_case_claim_unknown_policy_raises(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_basic", evidence_policy="bogus")

    [case] = load_corpus(corpus_root)
    config = stage_case(case, tmp_path / "work")

    with pytest.raises(ValueError, match="bogus"):
        build_case_claim(case, config)


# ---------------------------------------------------------------------------
# resolve_variant
# ---------------------------------------------------------------------------


def test_resolve_variant_default_matches_triage_system_prompt():
    variant = resolve_variant("baseline=@default")

    assert variant.name == "baseline"
    assert variant.system_prompt == TRIAGE_SYSTEM_PROMPT
    assert variant.prompt_source == "@default"
    assert variant.prompt_sha256 == hashlib.sha256(
        TRIAGE_SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()


def test_resolve_variant_omit_produces_different_prompt_and_hash():
    variant = resolve_variant("no_closing=@omit:closing")

    assert variant.name == "no_closing"
    assert variant.prompt_source == "@omit:closing"
    assert variant.system_prompt != TRIAGE_SYSTEM_PROMPT
    assert variant.prompt_sha256 != hashlib.sha256(
        TRIAGE_SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()


def test_resolve_variant_omit_unknown_section_raises():
    with pytest.raises(ValueError, match="unknown rubric sections"):
        resolve_variant("bad=@omit:not_a_real_section")


def test_resolve_variant_file_path_reads_text(tmp_path):
    prompt_path = tmp_path / "custom_prompt.txt"
    prompt_path.write_text("Custom system prompt text.", encoding="utf-8")

    variant = resolve_variant(f"custom={prompt_path}")

    assert variant.name == "custom"
    assert variant.system_prompt == "Custom system prompt text."
    assert variant.prompt_source == str(prompt_path)


def test_resolve_variant_missing_equals_raises():
    with pytest.raises(ValueError, match="name=value"):
        resolve_variant("bare_name_no_equals")


def test_resolve_variant_empty_name_raises():
    with pytest.raises(ValueError, match="empty variant name"):
        resolve_variant("=@default")


# ---------------------------------------------------------------------------
# cases_from_bootstrap_manifest
# ---------------------------------------------------------------------------


def _bootstrap_manifest_entry(**overrides) -> dict:
    base = {
        "slug": "boot-1",
        "origin": "fixture",
        "category": "dead_code",
        "adjudicated_verdict": "confirmed",
        "adjudication_notes": "notes go here",
        "finding": _finding_dict(symbol="boot_symbol_1", path="scripts/eval_lib.py"),
    }
    base.update(overrides)
    return base


def test_cases_from_bootstrap_manifest_wraps_entries(tmp_path):
    manifest = {
        "commit": "abc123",
        "entries": [
            _bootstrap_manifest_entry(slug="boot-1"),
            _bootstrap_manifest_entry(
                slug="boot-2",
                origin="audit",
                category="plumbing",
                adjudicated_verdict="dismissed",
                adjudication_notes="",
                gray=True,
                finding=_finding_dict(symbol="boot_symbol_2", path="scripts/eval_lib.py"),
            ),
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cases = cases_from_bootstrap_manifest(manifest_path)

    assert [c.key for c in cases] == ["boot-1", "boot-2"]
    assert all(c.source == "bootstrap" for c in cases)
    assert all(c.evidence_policy == "rebuild" for c in cases)
    assert all(c.snapshot_root == eval_lib.REPO_ROOT for c in cases)
    assert cases[0].category == "dead_code"
    assert cases[0].expected_verdict == "confirmed"
    assert cases[0].expected_reasoning == "notes go here"
    assert cases[0].gray is False
    assert isinstance(cases[0].finding, Finding)
    assert cases[0].finding.symbol == "boot_symbol_1"
    assert cases[1].category == "plumbing"
    assert cases[1].expected_verdict == "dismissed"
    assert cases[1].gray is True


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def _rec(**overrides) -> dict:
    base = {
        "schema": "osoji-verdict/1",
        "record": "verdict",
        "run_id": "run-1",
        "variant": "baseline",
        "repeat": 0,
        "source": "corpus",
        "case": "dead_code/case_101",
        "finding_id": "abc",
        "detector": "deadcode:dead_code",
        "category": "dead_code",
        "gap_type": "reachability",
        "path": "src/app/util.py",
        "symbol": "unused_helper",
        "line_start": 10,
        "line_end": 12,
        "expected_verdict": "confirmed",
        "gray": False,
        "verdict": "confirmed",
        "confidence": 0.9,
        "severity": "warning",
        "contract_class": None,
        "triage_reasoning": "because",
        "suggested_fix": "remove it",
        "insufficient_evidence": False,
        "evidence_policy": "rebuild",
        "correct": True,
    }
    base.update(overrides)
    return base


def _case(key, *, category="dead_code", gap_type="reachability", gray=False,
          path="src/app/util.py", symbol="unused_helper", line_start=10, line_end=12,
          detector="deadcode:dead_code") -> CorpusCase:
    finding = Finding(
        detector=detector,
        gap_type=gap_type,
        path=path,
        line_start=line_start,
        line_end=line_end,
        symbol=symbol,
        contract_source="declared",
        contract_claim="claim",
        observed_behavior="observed",
    )
    return CorpusCase(
        key=key,
        case_dir=Path(f"/fake/{key}"),
        category=category,
        finding=finding,
        expected_verdict="confirmed",
        expected_reasoning="",
        gray=gray,
        evidence_policy="rebuild",
        snapshot_root=Path(f"/fake/{key}"),
        origin={},
    )


def test_compute_metrics_tp_and_fp_rate():
    records = [
        _rec(case="c1", expected_verdict="confirmed", verdict="confirmed", gray=False),
        _rec(case="c2", expected_verdict="confirmed", verdict="dismissed", gray=False),
        _rec(case="c3", expected_verdict="confirmed", verdict=None, gray=False),
        _rec(case="c4", expected_verdict="dismissed", verdict="confirmed", gray=False),
        _rec(case="c5", expected_verdict="dismissed", verdict="dismissed", gray=False),
    ]
    cases = [_case(f"dead_code/{r['case']}") for r in records]

    metrics = compute_metrics(records, cases)

    # tp: 1 confirmed-correct out of 3 confirmed-expected (denominator includes
    # the dismissed and undecided evasions).
    assert metrics["tp_rate"] == pytest.approx(1 / 3)
    # fp: 1 wrongly-confirmed out of 2 dismissed-expected.
    assert metrics["fp_rate"] == pytest.approx(1 / 2)


def test_compute_metrics_tp_fp_rate_by_detector():
    records = [
        _rec(case="c1", detector="deadcode:dead_code", expected_verdict="confirmed", verdict="confirmed"),
        _rec(case="c2", detector="deadcode:dead_code", expected_verdict="confirmed", verdict="dismissed"),
        _rec(case="c3", detector="deadparam:dead_parameter", expected_verdict="dismissed", verdict="confirmed"),
    ]
    cases = [_case(f"dead_code/{r['case']}", detector=r["detector"]) for r in records]

    metrics = compute_metrics(records, cases)

    assert metrics["tp_rate_by_detector"]["deadcode:dead_code"] == pytest.approx(0.5)
    assert metrics["fp_rate_by_detector"]["deadparam:dead_parameter"] == pytest.approx(1.0)
    assert "deadparam:dead_parameter" not in metrics["tp_rate_by_detector"] or (
        metrics["tp_rate_by_detector"].get("deadparam:dead_parameter") == pytest.approx(0.0)
    )


def test_compute_metrics_excludes_gray_from_headline_metrics():
    records = [
        _rec(case="c1", expected_verdict="confirmed", verdict="dismissed", gray=False),
        _rec(case="c2", expected_verdict="confirmed", verdict="confirmed", gray=True),
    ]
    cases = [_case(f"dead_code/{r['case']}", gray=r["gray"]) for r in records]

    metrics = compute_metrics(records, cases)

    # Only the non-gray record counts: 0/1 tp.
    assert metrics["tp_rate"] == pytest.approx(0.0)


def test_compute_metrics_accuracy_nongray():
    records = [
        _rec(case="c1", expected_verdict="confirmed", verdict="confirmed", gray=False),
        _rec(case="c2", expected_verdict="dismissed", verdict="confirmed", gray=False),
        _rec(case="c3", expected_verdict="confirmed", verdict=None, gray=False),  # undecided, excluded
        _rec(case="c4", expected_verdict="confirmed", verdict="confirmed", gray=True),  # gray, excluded
    ]
    cases = [_case(f"dead_code/{r['case']}", gray=r["gray"]) for r in records]

    metrics = compute_metrics(records, cases)

    # Decided non-gray: c1 (correct), c2 (wrong) => 1/2.
    assert metrics["accuracy_nongray"] == pytest.approx(0.5)


def test_compute_metrics_ce_gap_gap_type_is_static_over_cases():
    cases = [
        _case("dead_code/c1", gap_type="reachability"),
        _case("dead_code/c2", gap_type="uncategorized"),
        _case("dead_code/c3", gap_type="uncategorized"),
        _case("dead_code/c4", gap_type="contract"),
    ]
    # Records are irrelevant to this metric — pass an empty list.
    metrics = compute_metrics([], cases)

    assert metrics["ce_gap_gap_type"] == pytest.approx(2 / 4)


def test_compute_metrics_ce_gap_contract_other():
    records = [
        _rec(case="c1", gap_type="contract", verdict="confirmed", contract_class="other"),
        _rec(case="c2", gap_type="contract", verdict="confirmed", contract_class="project_named"),
        _rec(case="c3", gap_type="contract", verdict=None, contract_class=None),  # undecided, excluded
        _rec(case="c4", gap_type="reachability", verdict="confirmed", contract_class=None),  # not contract
    ]
    cases = [_case(f"dead_code/{r['case']}") for r in records]

    metrics = compute_metrics(records, cases)

    assert metrics["ce_gap_contract_other"] == pytest.approx(1 / 2)


def test_compute_metrics_me_overlap():
    # Two findings, different producers, overlapping line ranges in the same
    # file: both count as overlapping. A third, non-overlapping finding does not.
    cases = [
        _case("dead_code/c1", detector="deadcode:dead_code", path="src/app/util.py",
              symbol="foo", line_start=10, line_end=15),
        _case("obligations/c2", detector="obligations:obligation_violation", path="src/app/util.py",
              symbol="bar", line_start=12, line_end=20),
        _case("dead_code/c3", detector="deadcode:dead_code", path="src/app/other.py",
              symbol="baz", line_start=1, line_end=2),
    ]

    metrics = compute_metrics([], cases)

    assert metrics["me_overlap"] == pytest.approx(2 / 3)


def test_compute_metrics_me_overlap_same_producer_does_not_overlap():
    cases = [
        _case("dead_code/c1", detector="deadcode:dead_code", path="src/app/util.py",
              symbol="foo", line_start=10, line_end=15),
        _case("dead_code/c2", detector="deadcode:dead_code", path="src/app/util.py",
              symbol="bar", line_start=12, line_end=20),
    ]

    metrics = compute_metrics([], cases)

    assert metrics["me_overlap"] == pytest.approx(0.0)


def test_compute_metrics_escalation_rate_rebuild_only():
    records = [
        _rec(case="c1", evidence_policy="rebuild", insufficient_evidence=True),
        _rec(case="c2", evidence_policy="rebuild", insufficient_evidence=False),
        _rec(case="c3", evidence_policy="frozen", insufficient_evidence=True),
    ]
    cases = [_case(f"dead_code/{r['case']}") for r in records]

    metrics = compute_metrics(records, cases)

    assert metrics["escalation_denominator"] == 2
    assert metrics["escalation_rate"] == pytest.approx(0.5)


def test_compute_metrics_uncertain_and_undecided_rates():
    records = [
        _rec(case="c1", verdict="confirmed"),
        _rec(case="c2", verdict="uncertain"),
        _rec(case="c3", verdict=None),
        _rec(case="c4", verdict=None),
    ]
    cases = [_case(f"dead_code/{r['case']}") for r in records]

    metrics = compute_metrics(records, cases)

    assert metrics["uncertain_rate"] == pytest.approx(0.25)
    assert metrics["undecided_rate"] == pytest.approx(0.5)


def test_compute_metrics_gray_count_and_n_cases_and_per_category():
    cases = [
        _case("dead_code/c1", category="dead_code", gray=False),
        _case("dead_code/c2", category="dead_code", gray=True),
        _case("plumbing/c3", category="plumbing", gray=False),
    ]

    metrics = compute_metrics([], cases)

    assert metrics["gray_count"] == 1
    assert metrics["n_cases"] == 3
    assert metrics["n_cases_by_category"] == {"dead_code": 2, "plumbing": 1}


def test_compute_metrics_empty_inputs_do_not_crash():
    metrics = compute_metrics([], [])

    assert metrics["tp_rate"] == 0.0
    assert metrics["fp_rate"] == 0.0
    assert metrics["accuracy_nongray"] == 0.0
    assert metrics["ce_gap_gap_type"] == 0.0
    assert metrics["me_overlap"] == 0.0
    assert metrics["escalation_rate"] == 0.0
    assert metrics["n_cases"] == 0


# ---------------------------------------------------------------------------
# NDJSON
# ---------------------------------------------------------------------------


def test_write_read_verdict_ndjson_round_trip(tmp_path):
    records = [_rec(case="c1"), _rec(case="c2", verdict="dismissed", expected_verdict="dismissed")]
    run_meta = {
        "schema": "osoji-verdict/1",
        "record": "run_meta",
        "run_id": "run-1",
        "started_at": "2026-07-21T00:00:00Z",
        "finished_at": "2026-07-21T00:01:00Z",
        "duration_s": 60.0,
        "variants": {"baseline": {"prompt_sha256": "deadbeef", "prompt_source": "triage.py"}},
        "provider": "anthropic",
        "model": "claude-test",
        "osoji_commit": "abc123",
        "claim_builder_schema_version": "cb-3",
        "corpus": {"root": "tests/fixtures/prompt_regression", "n_cases": 2, "n_gray": 0,
                   "split": None, "only": None, "exclude_gray": False},
        "repeats": 1,
        "repeat_offset": 0,
        "batch_size": 12,
        "tokens": {"input": 100, "output": 50},
        "metrics": {"tp_rate": 1.0},
    }

    out_path = tmp_path / "runs" / "run-1.ndjson"
    write_verdict_ndjson(records, run_meta, out_path)
    read_records, read_meta = read_verdict_ndjson(out_path)

    assert read_records == records
    assert read_meta == run_meta


def test_write_verdict_ndjson_trailer_is_last_line(tmp_path):
    records = [_rec(case="c1"), _rec(case="c2")]
    run_meta = {"schema": "osoji-verdict/1", "record": "run_meta", "run_id": "run-1"}

    out_path = tmp_path / "run.ndjson"
    write_verdict_ndjson(records, run_meta, out_path)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines[:-1]:
        assert json.loads(line)["record"] == "verdict"
    assert json.loads(lines[-1])["record"] == "run_meta"


def test_write_verdict_ndjson_uses_lf_and_no_bom(tmp_path):
    out_path = tmp_path / "run.ndjson"
    write_verdict_ndjson([_rec(case="c1")], {"schema": "osoji-verdict/1", "record": "run_meta", "run_id": "r"}, out_path)

    raw = out_path.read_bytes()
    assert b"\r\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")


def test_write_verdict_ndjson_writes_to_open_stream():
    stream = io.StringIO()
    records = [_rec(case="c1"), _rec(case="c2")]
    run_meta = {"schema": "osoji-verdict/1", "record": "run_meta", "run_id": "run-1"}

    write_verdict_ndjson(records, run_meta, stream)

    content = stream.getvalue()
    assert "\r\n" not in content
    lines = content.splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["case"] == "c1"
    assert json.loads(lines[1])["case"] == "c2"
    assert json.loads(lines[2])["record"] == "run_meta"


def test_write_verdict_ndjson_writes_to_open_file_object(tmp_path):
    path = tmp_path / "run.ndjson"
    records = [_rec(case="c1")]
    run_meta = {"schema": "osoji-verdict/1", "record": "run_meta", "run_id": "run-1"}

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        write_verdict_ndjson(records, run_meta, fh)

    read_records, read_meta = read_verdict_ndjson(path)
    assert read_records == records
    assert read_meta == run_meta


def test_read_verdict_ndjson_empty_file_raises(tmp_path):
    path = tmp_path / "empty.ndjson"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        read_verdict_ndjson(path)


def test_read_verdict_ndjson_rejects_stream_with_no_run_meta(tmp_path):
    out_path = tmp_path / "bad.ndjson"
    lines = [json.dumps(_rec(case="c1")), json.dumps(_rec(case="c2"))]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="run_meta"):
        read_verdict_ndjson(out_path)


def test_read_verdict_ndjson_rejects_bad_record_schema(tmp_path):
    out_path = tmp_path / "bad.ndjson"
    bad_record = _rec(case="c1")
    bad_record["schema"] = "osoji-verdict/99"
    lines = [json.dumps(bad_record), json.dumps({"schema": "osoji-verdict/1", "record": "run_meta", "run_id": "r"})]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        read_verdict_ndjson(out_path)


# ---------------------------------------------------------------------------
# load_splits
# ---------------------------------------------------------------------------


def test_load_splits_reads_valid_file(tmp_path):
    path = tmp_path / "splits.json"
    data = {
        "schema": "corpus-splits/1",
        "seed": 42,
        "ratios": {"train": 0.5, "val": 0.25, "holdout": 0.25},
        "assignments": {"dead_code/case_101_a": "train"},
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_splits(path)

    assert loaded == data


def test_load_splits_bad_schema_raises(tmp_path):
    path = tmp_path / "splits.json"
    path.write_text(json.dumps({"schema": "corpus-splits/99"}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_splits(path)


# ---------------------------------------------------------------------------
# suggest_split
# ---------------------------------------------------------------------------


def test_suggest_split_is_deterministic():
    ratios = {"train": 0.5, "val": 0.25, "holdout": 0.25}

    first = suggest_split("dead_code/case_101_a", 42, ratios)
    second = suggest_split("dead_code/case_101_a", 42, ratios)

    assert first == second
    assert first in ratios


def test_suggest_split_differs_by_seed_for_some_keys():
    ratios = {"train": 0.5, "val": 0.5}
    keys = [f"dead_code/case_{i}" for i in range(50)]

    assignments_seed_a = {k: suggest_split(k, 1, ratios) for k in keys}
    assignments_seed_b = {k: suggest_split(k, 2, ratios) for k in keys}

    assert assignments_seed_a != assignments_seed_b


def test_suggest_split_respects_ratios_roughly(tmp_path):
    ratios = {"train": 0.5, "val": 0.25, "holdout": 0.25}
    keys = [f"dead_code/case_{i}" for i in range(2000)]

    counts = {"train": 0, "val": 0, "holdout": 0}
    for k in keys:
        counts[suggest_split(k, 7, ratios)] += 1

    total = len(keys)
    assert counts["train"] / total == pytest.approx(0.5, abs=0.05)
    assert counts["val"] / total == pytest.approx(0.25, abs=0.05)
    assert counts["holdout"] / total == pytest.approx(0.25, abs=0.05)


# ---------------------------------------------------------------------------
# check_gepa_gate
# ---------------------------------------------------------------------------


def test_check_gepa_gate_passes_when_covered_and_enough_nongray_cases():
    cases = [_case(f"dead_code/c{i}") for i in range(90)]
    splits = {"assignments": {c.key: "train" for c in cases}}

    report = check_gepa_gate(cases, splits, required=90)

    assert report.nongray_count == 90
    assert report.splits_nonempty is True
    assert report.coverage_ok is True
    assert report.missing_from_splits == []
    assert report.extra_in_splits == []
    assert report.passed is True


def test_check_gepa_gate_fails_when_nongray_count_short():
    cases = [_case(f"dead_code/c{i}") for i in range(50)]
    splits = {"assignments": {c.key: "train" for c in cases}}

    report = check_gepa_gate(cases, splits, required=90)

    assert report.nongray_count == 50
    assert report.coverage_ok is True
    assert report.passed is False


def test_check_gepa_gate_fails_on_empty_splits():
    cases = [_case(f"dead_code/c{i}") for i in range(90)]
    splits = {"assignments": {}}

    report = check_gepa_gate(cases, splits, required=90)

    assert report.splits_nonempty is False
    assert report.passed is False


def test_check_gepa_gate_fails_on_missing_from_splits():
    cases = [_case(f"dead_code/c{i}") for i in range(90)]
    assignments = {c.key: "train" for c in cases[:-1]}  # last case has no assignment
    splits = {"assignments": assignments}

    report = check_gepa_gate(cases, splits, required=90)

    assert report.coverage_ok is False
    assert report.missing_from_splits == ["dead_code/c89"]
    assert report.extra_in_splits == []
    assert report.passed is False


def test_check_gepa_gate_fails_on_extra_in_splits():
    cases = [_case(f"dead_code/c{i}") for i in range(90)]
    assignments = {c.key: "train" for c in cases}
    assignments["dead_code/stale_no_longer_exists"] = "val"
    splits = {"assignments": assignments}

    report = check_gepa_gate(cases, splits, required=90)

    assert report.coverage_ok is False
    assert report.extra_in_splits == ["dead_code/stale_no_longer_exists"]
    assert report.missing_from_splits == []
    assert report.passed is False


# ---------------------------------------------------------------------------
# evaluate_corpus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_corpus_fake_provider_e2e(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root, "dead_code", "case_101_a",
        verdict="confirmed",
        source_files={"src/app/a.py": "def unused_a():\n    pass\n"},
        finding_overrides={
            "path": "src/app/a.py", "symbol": "unused_a",
            "contract_claim": "unused_a is defined at module scope",
        },
    )
    make_case(
        corpus_root, "dead_code", "case_102_b",
        verdict="dismissed",
        source_files={"src/app/b.py": "def unused_b():\n    pass\n"},
        finding_overrides={
            "path": "src/app/b.py", "symbol": "unused_b",
            "contract_claim": "unused_b is defined at module scope",
        },
    )
    cases = load_corpus(corpus_root)
    assert len(cases) == 2

    variants = [
        Variant(name="baseline", system_prompt="BASELINE PROMPT", prompt_source="@default"),
        Variant(name="no_closing", system_prompt="ALT PROMPT", prompt_source="@omit:closing"),
    ]

    # 2 variants x 2 repeats = 4 decide_junk_claims calls; both claims fit in
    # one BATCH_SIZE chunk each time, so each call is exactly 1 provider.complete().
    full_verdicts = [
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "r0"},
        {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "r1"},
    ]
    # Only batch_index 0 decided: claim 1 (case_102_b) stays undecided (verdict=None).
    partial_verdicts = [
        {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "r0-partial"},
    ]
    provider = FakeProvider([
        verdicts_result(full_verdicts, in_tok=100, out_tok=40),     # baseline, repeat 0
        verdicts_result(partial_verdicts, in_tok=50, out_tok=20),   # baseline, repeat 1 (null case)
        verdicts_result(full_verdicts, in_tok=100, out_tok=40),     # no_closing, repeat 0
        verdicts_result(full_verdicts, in_tok=100, out_tok=40),     # no_closing, repeat 1
    ])

    run = await evaluate_corpus(
        cases,
        variants,
        repeats=2,
        repeat_offset=10,
        run_id="test-run",
        provider=provider,
        config_factory=lambda: Config(
            root_path=tmp_path, provider="anthropic", model="test-model", respect_gitignore=False
        ),
        workdir=tmp_path / "work",
        corpus_root=corpus_root,
    )

    assert len(provider.calls) == 4
    assert len(run.records) == 8

    # repeat numbering with offset: k in range(2) + repeat_offset=10 -> {10, 11}
    reps_by_variant: dict[str, set[int]] = {}
    for r in run.records:
        reps_by_variant.setdefault(r["variant"], set()).add(r["repeat"])
    assert reps_by_variant == {"baseline": {10, 11}, "no_closing": {10, 11}}

    # The null-verdict case: baseline/repeat 11, case_102_b -> verdict None, correct None.
    null_records = [r for r in run.records if r["verdict"] is None]
    assert len(null_records) == 1
    (null_record,) = null_records
    assert null_record["variant"] == "baseline"
    assert null_record["repeat"] == 11
    assert null_record["case"] == "dead_code/case_102_b"
    assert null_record["correct"] is None
    assert null_record["source"] == "corpus"

    # correctness: case_101_a expects "confirmed", case_102_b expects "dismissed"
    for r in run.records:
        if r["verdict"] is None:
            continue
        if r["case"] == "dead_code/case_101_a":
            assert r["verdict"] == "confirmed"
            assert r["correct"] is True
        elif r["case"] == "dead_code/case_102_b":
            assert r["verdict"] == "dismissed"
            assert r["correct"] is True

    assert run.run_meta["tokens"]["input"] == 100 + 50 + 100 + 100
    assert run.run_meta["tokens"]["output"] == 40 + 20 + 40 + 40

    meta = run.run_meta
    for key in (
        "schema", "record", "run_id", "started_at", "finished_at", "duration_s",
        "variants", "provider", "model", "osoji_commit", "claim_builder_schema_version",
        "corpus", "repeats", "repeat_offset", "batch_size", "tokens", "metrics",
    ):
        assert key in meta, f"run_meta missing {key!r}"
    assert meta["schema"] == "osoji-verdict/1"
    assert meta["record"] == "run_meta"
    assert meta["run_id"] == "test-run"
    assert meta["provider"] == "anthropic"
    assert meta["model"] == "test-model"
    assert meta["repeats"] == 2
    assert meta["repeat_offset"] == 10
    assert meta["batch_size"] == eval_lib.JUNK_BATCH_SIZE
    assert meta["variants"] == {
        "baseline": {
            "prompt_sha256": hashlib.sha256(b"BASELINE PROMPT").hexdigest(),
            "prompt_source": "@default",
        },
        "no_closing": {
            "prompt_sha256": hashlib.sha256(b"ALT PROMPT").hexdigest(),
            "prompt_source": "@omit:closing",
        },
    }
    assert meta["corpus"]["n_cases"] == 2
    assert meta["corpus"]["n_gray"] == 0
    assert meta["corpus"]["root"] == str(corpus_root)

    # records-then-trailer ordering via write_verdict_ndjson, full round trip.
    out_path = tmp_path / "run.ndjson"
    write_verdict_ndjson(run.records, run.run_meta, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 9
    for line in lines[:-1]:
        assert json.loads(line)["record"] == "verdict"
    assert json.loads(lines[-1])["record"] == "run_meta"

    read_records, read_meta = read_verdict_ndjson(out_path)
    assert read_records == run.records
    assert read_meta == run.run_meta


@pytest.mark.asyncio
async def test_evaluate_corpus_mixes_corpus_and_bootstrap_sources(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a", verdict="confirmed")
    [corpus_case] = load_corpus(corpus_root)

    bootstrap_case = CorpusCase(
        key="bootstrap-slug-1",
        case_dir=eval_lib.REPO_ROOT,
        category="dead_code",
        finding=Finding(
            detector="debris:dead_code",
            gap_type="reachability",
            path="scripts/eval_lib.py",
            line_start=1,
            line_end=1,
            symbol="CORPUS_ROOT",
            contract_source="symbol declaration",
            contract_claim="CORPUS_ROOT is declared but appears unused",
            observed_behavior="synthetic bootstrap case for the mixed-source test",
        ),
        expected_verdict="dismissed",
        expected_reasoning="",
        gray=False,
        evidence_policy="rebuild",
        snapshot_root=eval_lib.REPO_ROOT,
        origin={},
        source="bootstrap",
    )

    cases = [corpus_case, bootstrap_case]
    variants = [Variant(name="baseline", system_prompt="P", prompt_source="@default")]
    provider = FakeProvider([
        verdicts_result([
            {"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "r0"},
            {"batch_index": 1, "verdict": "dismissed", "confidence": 0.8, "reasoning": "r1"},
        ]),
    ])

    run = await evaluate_corpus(
        cases,
        variants,
        provider=provider,
        config_factory=lambda: Config(
            root_path=tmp_path, provider="anthropic", model="m", respect_gitignore=False
        ),
        workdir=tmp_path / "work",
    )

    # Claims from both sources are self-sufficient and decided in ONE pass.
    assert len(provider.calls) == 1
    assert len(run.records) == 2
    by_case = {r["case"]: r for r in run.records}
    assert by_case["dead_code/case_101_a"]["source"] == "corpus"
    assert by_case["bootstrap-slug-1"]["source"] == "bootstrap"
    assert by_case["bootstrap-slug-1"]["evidence_policy"] == "rebuild"


@pytest.mark.asyncio
async def test_evaluate_corpus_empty_cases_raises():
    with pytest.raises(ValueError, match="cases is empty"):
        await evaluate_corpus(
            [], [Variant(name="baseline", system_prompt="P", prompt_source="@default")],
            provider=FakeProvider([]), workdir=Path("."),
        )


@pytest.mark.asyncio
async def test_evaluate_corpus_empty_variants_raises(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a")
    cases = load_corpus(corpus_root)

    with pytest.raises(ValueError, match="variants is empty"):
        await evaluate_corpus(cases, [], provider=FakeProvider([]), workdir=Path("."))


# ---------------------------------------------------------------------------
# evaluate_corpus: owned-provider lifecycle (review Important 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_corpus_staging_failure_never_constructs_provider(tmp_path, monkeypatch):
    """A staging failure must happen before any provider is constructed —
    otherwise an owned provider's async client would be opened and never
    closed (the try/finally only wraps the decide loop, not staging)."""

    corpus_root = tmp_path / "corpus"
    make_case(
        corpus_root, "dead_code", "case_101_bad",
        evidence_policy="rebuild", write_source=False,
    )
    cases = load_corpus(corpus_root)

    constructed: list[str] = []

    def spy_create_provider(name):
        constructed.append(name)
        return FakeProvider([])

    monkeypatch.setattr(eval_lib, "create_provider", spy_create_provider)
    variants = [Variant(name="baseline", system_prompt="P", prompt_source="@default")]

    with pytest.raises(ValueError, match="case_101_bad"):
        await evaluate_corpus(
            cases,
            variants,
            provider=None,  # not injected: evaluate_corpus would own/construct one
            config_factory=lambda: Config(
                root_path=tmp_path, provider="anthropic", model="m", respect_gitignore=False
            ),
            workdir=tmp_path / "work",
        )

    assert constructed == []


@pytest.mark.asyncio
async def test_evaluate_corpus_constructs_and_closes_owned_provider(tmp_path, monkeypatch):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a", verdict="confirmed")
    cases = load_corpus(corpus_root)

    fake = FakeProvider([
        verdicts_result(
            [{"batch_index": 0, "verdict": "confirmed", "confidence": 0.9, "reasoning": "r"}]
        ),
    ])
    constructed: list[str] = []

    def spy_create_provider(name):
        constructed.append(name)
        return fake

    monkeypatch.setattr(eval_lib, "create_provider", spy_create_provider)
    variants = [Variant(name="baseline", system_prompt="P", prompt_source="@default")]

    run = await evaluate_corpus(
        cases,
        variants,
        provider=None,
        config_factory=lambda: Config(
            root_path=tmp_path, provider="anthropic", model="m", respect_gitignore=False
        ),
        workdir=tmp_path / "work",
    )

    assert constructed == ["anthropic"]
    assert fake.closed is True
    assert len(run.records) == 1


# ---------------------------------------------------------------------------
# select_cases
# ---------------------------------------------------------------------------


def test_select_cases_corpus_source(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a")

    cases = select_cases(source="corpus", corpus_root=corpus_root)

    assert [c.key for c in cases] == ["dead_code/case_101_a"]


def test_select_cases_bootstrap_source(tmp_path):
    manifest = {"commit": "abc", "entries": [_bootstrap_manifest_entry(slug="boot-1")]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cases = select_cases(source="bootstrap", bootstrap_manifest=manifest_path)

    assert [c.key for c in cases] == ["boot-1"]


def test_select_cases_both_sources_merged(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a")
    manifest = {"commit": "abc", "entries": [_bootstrap_manifest_entry(slug="boot-1")]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cases = select_cases(
        source="both", corpus_root=corpus_root, bootstrap_manifest=manifest_path
    )

    assert {c.key for c in cases} == {"dead_code/case_101_a", "boot-1"}


def test_select_cases_only_filters_both_sources(tmp_path):
    corpus_root = tmp_path / "corpus"
    make_case(corpus_root, "dead_code", "case_101_a")
    manifest = {
        "commit": "abc",
        "entries": [
            _bootstrap_manifest_entry(slug="boot-1"),
            _bootstrap_manifest_entry(slug="boot-2"),
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cases = select_cases(
        source="both", corpus_root=corpus_root, bootstrap_manifest=manifest_path,
        only=["boot-1"],
    )

    assert [c.key for c in cases] == ["boot-1"]


def test_select_cases_bootstrap_without_manifest_raises(tmp_path):
    with pytest.raises(ValueError, match="bootstrap_manifest"):
        select_cases(source="bootstrap", bootstrap_manifest=None)
