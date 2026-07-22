"""Structural validation of the committed V1-7 corpus (osojicode/work#35).

Unmarked — collected in every default CI run, no LLM calls, no network. Walks
the REAL tree under ``eval_lib.CORPUS_ROOT`` (never a synthetic ``tmp_path``
corpus — that's ``tests/test_eval_lib.py``'s job) and checks the invariants
that make the corpus safe to load and replay: schema tags, acceptance,
``Finding`` round-tripping, ``splits.json`` coverage, path safety, and the
``rebuild``-policy ``source/`` non-empty rule.

The corpus is EMPTY today (only ``_holding/.gitkeep``, ``README.md``, and an
assignment-less ``splits.json``) — every test here must pass against that
empty tree and stay meaningful once cases land: each iterates the real case
set and asserts nothing when that set is empty, rather than asserting a
specific non-zero count.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import eval_lib  # noqa: E402
from osoji.findings import Finding  # noqa: E402

BASELINE_PATH = eval_lib.CORPUS_ROOT / "evaluate-baseline.json"


def _case_json_paths() -> list[Path]:
    """Every ``case.json`` under the corpus, excluding ``_holding/``.

    Mirrors ``load_corpus``'s own glob and holding-exclusion exactly, but
    (unlike ``load_corpus``) does NOT filter out unaccepted cases — this is
    the raw universe ``test_every_case_json_...`` below checks acceptance
    over.
    """

    paths = []
    for case_json_path in sorted(eval_lib.CORPUS_ROOT.glob("*/case_*/case.json")):
        rel_dir = case_json_path.parent.relative_to(eval_lib.CORPUS_ROOT)
        if "_holding" in rel_dir.parts:
            continue
        paths.append(case_json_path)
    return paths


# ---------------------------------------------------------------------------
# case.json / expected.json schema + acceptance
# ---------------------------------------------------------------------------


def test_every_case_json_parses_with_valid_schema_and_is_accepted():
    for case_json_path in _case_json_paths():
        case_data = json.loads(case_json_path.read_text(encoding="utf-8"))
        assert case_data.get("schema") == eval_lib.CORPUS_CASE_SCHEMA, (
            f"{case_json_path}: bad case.json schema tag {case_data.get('schema')!r}"
        )

        expected_path = case_json_path.parent / "expected.json"
        expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
        assert expected_data.get("schema") == eval_lib.CORPUS_EXPECTED_SCHEMA, (
            f"{expected_path}: bad expected.json schema tag {expected_data.get('schema')!r}"
        )
        assert expected_data.get("accepted") is True, (
            f"{expected_path}: every case outside _holding/ must be accepted "
            "(unreviewed sweep output belongs under _holding/, not here)"
        )


# ---------------------------------------------------------------------------
# finding.json round-trip
# ---------------------------------------------------------------------------


def test_every_finding_json_round_trips_through_finding_preserving_id():
    for case_json_path in _case_json_paths():
        finding_path = case_json_path.parent / "finding.json"
        data = json.loads(finding_path.read_text(encoding="utf-8"))

        finding = Finding.from_dict(data)
        round_tripped = Finding.from_dict(finding.to_dict())

        assert round_tripped.id == finding.id, finding_path
        if data.get("id"):
            assert finding.id == data["id"], (
                f"{finding_path}: a non-empty stored id must survive from_dict verbatim"
            )


# ---------------------------------------------------------------------------
# splits.json
# ---------------------------------------------------------------------------


def test_splits_json_parses_and_covers_accepted_case_keys_exactly():
    splits = eval_lib.load_splits(eval_lib.CORPUS_ROOT / "splits.json")
    assert splits.get("schema") == eval_lib.CORPUS_SPLITS_SCHEMA

    accepted_keys = {c.key for c in eval_lib.load_corpus()}
    assignment_keys = set(splits.get("assignments", {}))

    missing = sorted(accepted_keys - assignment_keys)
    extra = sorted(assignment_keys - accepted_keys)
    assert not missing, f"case keys missing from splits.json assignments: {missing}"
    assert not extra, f"stale/unknown keys in splits.json assignments: {extra}"


# ---------------------------------------------------------------------------
# Path safety: no absolute paths, no ".." traversal
# ---------------------------------------------------------------------------

_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[/\\]")


def _unsafe_path_reason(value: object) -> str | None:
    """Reason string if ``value`` looks like an absolute or traversal path.

    ``None`` means ``value`` isn't a string, is empty, or looks like a safe
    corpus-relative POSIX path. Every corpus path is documented (README.md)
    as POSIX and repo/corpus-root-relative for any language, any project —
    so this recognizes POSIX-root, drive-letter, and UNC absolute forms
    regardless of which platform wrote the fixture.
    """

    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("//"):
        return "absolute (UNC)"
    if normalized.startswith("/"):
        return "absolute (POSIX-rooted)"
    if _DRIVE_LETTER_RE.match(normalized):
        return "absolute (drive-letter)"
    if any(part == ".." for part in normalized.split("/")):
        return "contains a '..' traversal segment"
    return None


def _path_like_strings(obj: object, context: str = "") -> list[tuple[str, str]]:
    """Recursively collect (context, value) for every string under a key
    whose name contains "path" (case-insensitive), anywhere in ``obj``."""

    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            ctx = f"{context}.{key}" if context else str(key)
            if isinstance(value, str) and "path" in key.lower():
                found.append((ctx, value))
            else:
                found.extend(_path_like_strings(value, ctx))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(_path_like_strings(value, f"{context}[{i}]"))
    return found


def test_no_absolute_or_traversal_paths_in_case_finding_or_evidence():
    violations = []
    for case_json_path in _case_json_paths():
        case_data = json.loads(case_json_path.read_text(encoding="utf-8"))
        snapshot_ref = case_data.get("snapshot_ref")
        if snapshot_ref:
            reason = _unsafe_path_reason(snapshot_ref)
            if reason:
                violations.append(f"{case_json_path}: snapshot_ref {snapshot_ref!r} is {reason}")

        finding_path = case_json_path.parent / "finding.json"
        finding_data = json.loads(finding_path.read_text(encoding="utf-8"))
        reason = _unsafe_path_reason(finding_data.get("path"))
        if reason:
            violations.append(f"{finding_path}: path {finding_data.get('path')!r} is {reason}")

        for ctx, value in _path_like_strings(finding_data.get("evidence") or []):
            reason = _unsafe_path_reason(value)
            if reason:
                violations.append(f"{finding_path}: evidence{ctx} {value!r} is {reason}")

    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# No nested fixture snapshots inside a case's source/ (osojicode/work#85)
# ---------------------------------------------------------------------------

# A case's ``source/`` is a mini-repo snapshot the audit walker captured. When
# the repo it snapshotted was osoji's OWN tree, the walker swept the committed
# corpus/bootstrap fixtures back into the snapshot, embedding whole fixture
# trees under ``source/``. That both pollutes replay evidence (mechanism 1 of
# work#85) and — because the nesting multiplies path depth — pushes committed
# paths past Windows MAX_PATH, breaking ``git clone``/``git worktree add`` on
# any checkout without ``core.longpaths``. These tests are the structural guard
# against re-committing such snapshots.

# Marker directories whose appearance ANYWHERE under a case's source/ means a
# frozen copy of the corpus or bootstrap fixture tree leaked into the snapshot.
_NESTED_SNAPSHOT_MARKERS = (
    ("tests", "fixtures", "prompt_regression"),
    ("tests", "fixtures", "bootstrap"),
)

# Every committed path is resolved on a fresh clone as ``<repo-root-abs>/<this>``.
# Bounding the repo-root-relative path here leaves headroom under Windows
# MAX_PATH (260) for the absolute repo-root prefix a clone/worktree prepends.
_MAX_REPO_RELATIVE_PATH_LEN = 180


def _has_nested_marker(rel_parts: tuple[str, ...]) -> bool:
    """True if ``rel_parts`` (a case-source-relative path) descends through a
    ``tests/fixtures/prompt_regression`` or ``tests/fixtures/bootstrap`` dir."""

    for marker in _NESTED_SNAPSHOT_MARKERS:
        n = len(marker)
        for i in range(len(rel_parts) - n + 1):
            if rel_parts[i : i + n] == marker:
                return True
    return False


def test_no_nested_fixture_snapshots_under_case_source():
    violations = []
    for case_json_path in _case_json_paths():
        source_dir = case_json_path.parent / "source"
        if not source_dir.is_dir():
            continue
        for p in source_dir.rglob("*"):
            if not p.is_file():
                continue
            rel_parts = p.relative_to(source_dir).parts
            if _has_nested_marker(rel_parts):
                violations.append(str(p.relative_to(REPO_ROOT).as_posix()))

    assert not violations, (
        "nested fixture snapshots leaked into case source/ trees "
        "(osojicode/work#85 evidence pollution):\n" + "\n".join(sorted(violations))
    )


def test_no_case_path_exceeds_windows_safe_length():
    violations = []
    for case_json_path in _case_json_paths():
        case_dir = case_json_path.parent
        for p in case_dir.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            if len(rel) > _MAX_REPO_RELATIVE_PATH_LEN:
                violations.append(f"{len(rel)} chars: {rel}")

    assert not violations, (
        f"committed corpus paths exceed {_MAX_REPO_RELATIVE_PATH_LEN} chars "
        "(Windows MAX_PATH headroom, osojicode/work#85):\n"
        + "\n".join(sorted(violations, reverse=True))
    )


# ---------------------------------------------------------------------------
# rebuild-policy cases carry a non-empty source/
# ---------------------------------------------------------------------------


def test_rebuild_policy_cases_have_nonempty_source():
    for case in eval_lib.load_corpus():
        if case.evidence_policy != "rebuild":
            continue
        source_dir = case.snapshot_root / "source"
        assert source_dir.is_dir(), (
            f"{case.key}: evidence_policy=rebuild but no source/ under {case.snapshot_root}"
        )
        assert any(p.is_file() for p in source_dir.rglob("*")), (
            f"{case.key}: source/ under {case.snapshot_root} is empty"
        )


# ---------------------------------------------------------------------------
# Static metrics smoke + threshold gate
# ---------------------------------------------------------------------------


def test_static_metrics_smoke_and_threshold_gate():
    cases = eval_lib.load_corpus()
    metrics = eval_lib.compute_metrics([], cases)

    print(
        f"\ncorpus static metrics: n_cases={metrics['n_cases']} "
        f"ce_gap_gap_type={metrics['ce_gap_gap_type']:.1%} "
        f"me_overlap={metrics['me_overlap']:.1%}"
    )

    if not BASELINE_PATH.exists():
        print("no evaluate-baseline.json; thresholds not enforced")
        return

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    static_metrics = {
        "ce_gap_gap_type": metrics["ce_gap_gap_type"],
        "me_overlap": metrics["me_overlap"],
    }
    violations = eval_lib.check_thresholds(static_metrics, baseline)
    assert not violations, "\n".join(violations)


# ---------------------------------------------------------------------------
# _holding/ is unreachable via load_corpus
# ---------------------------------------------------------------------------


def test_holding_contents_unreachable_via_load_corpus():
    keys = {c.key for c in eval_lib.load_corpus()}
    holding_keys = [key for key in keys if key.startswith("_holding")]
    assert not holding_keys, f"load_corpus returned _holding/ entries: {holding_keys}"


# ---------------------------------------------------------------------------
# check_thresholds (eval_lib) — pure function, unit-tested here since this
# is the only file this task adds besides the one --evaluate test.
# ---------------------------------------------------------------------------


def test_check_thresholds_passes_within_bounds():
    metrics = {"fp_rate": 0.1, "tp_rate": 0.9}
    baseline = {"fp_rate": {"max": 0.2}, "tp_rate": {"min": 0.8}}

    assert eval_lib.check_thresholds(metrics, baseline) == []


def test_check_thresholds_reports_max_violation():
    metrics = {"fp_rate": 0.35}
    baseline = {"fp_rate": {"max": 0.2}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "fp_rate" in violations[0]
    assert "0.35" in violations[0]
    assert "0.2" in violations[0]


def test_check_thresholds_reports_min_violation():
    metrics = {"tp_rate": 0.5}
    baseline = {"tp_rate": {"min": 0.8}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "tp_rate" in violations[0]


def test_check_thresholds_checks_both_bounds_for_one_metric():
    metrics = {"accuracy_nongray": 0.5}
    baseline = {"accuracy_nongray": {"min": 0.6, "max": 0.9}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "below min" in violations[0]


def test_check_thresholds_skips_baseline_metric_absent_from_metrics():
    metrics = {"ce_gap_gap_type": 0.1}
    baseline = {"ce_gap_gap_type": {"max": 0.2}, "tp_rate": {"min": 0.8}}

    assert eval_lib.check_thresholds(metrics, baseline) == []


def test_check_thresholds_skips_non_scalar_metric_values():
    metrics = {"tp_rate_by_detector": {"deadcode:dead_code": 0.99}}
    baseline = {"tp_rate_by_detector": {"max": 0.5}}

    assert eval_lib.check_thresholds(metrics, baseline) == []


def test_check_thresholds_empty_baseline_yields_no_violations():
    assert eval_lib.check_thresholds({"fp_rate": 0.99}, {}) == []


def test_check_thresholds_reports_non_dict_bounds_as_violation():
    """A bare-number/string baseline entry (malformed JSON, not the
    ``{"max": ...}``/``{"min": ...}`` shape) must surface as a violation
    naming the metric and the malformed value, not raise TypeError."""
    metrics = {"fp_rate": 0.1}
    baseline = {"fp_rate": 0.2}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "fp_rate" in violations[0]
    assert "0.2" in violations[0]


def test_check_thresholds_reports_dict_bounds_missing_min_and_max():
    metrics = {"fp_rate": 0.1}
    baseline = {"fp_rate": {"note": "todo"}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "fp_rate" in violations[0]


def test_check_thresholds_reports_non_numeric_bound_value():
    metrics = {"fp_rate": 0.1}
    baseline = {"fp_rate": {"max": "high"}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 1
    assert "fp_rate" in violations[0]
    assert "high" in violations[0]


def test_check_thresholds_malformed_entry_does_not_block_other_metrics():
    """One malformed baseline entry must not raise and must not prevent a
    sibling metric's own (valid) violation from being reported."""
    metrics = {"fp_rate": 0.35, "tp_rate": 0.9}
    baseline = {"fp_rate": "not-a-dict", "tp_rate": {"min": 0.95}}

    violations = eval_lib.check_thresholds(metrics, baseline)

    assert len(violations) == 2
    joined = "\n".join(violations)
    assert "fp_rate" in joined
    assert "tp_rate" in joined
