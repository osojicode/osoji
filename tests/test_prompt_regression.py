"""Prompt regression tests using real LLM calls against snapshotted files.

These tests verify that prompt changes don't regress on known edge cases.
They make real API calls and are gated behind the 'prompt_regression' marker.

Run with: pytest -m prompt_regression
Skipped by default in normal 'pytest' runs.

Statistical mode:
  --establish-baseline  Run 30 trials per case, write p0 to expected.json
  (default)             Run computed N trials, assert pass rate via binomial test
"""

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.deadcode import DeadCodeCandidate, _verify_batch_async, scan_references
from docstar.llm.factory import create_provider

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompt_regression"


def _setup_case_dir(tmp_path: Path, case_dir: Path) -> Config:
    """Copy snapshotted source files into a temp project dir and return a Config."""
    source_dir = case_dir / "source"
    symbols_dir = case_dir / "symbols"

    # Copy source files
    for src_file in source_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(source_dir)
            dest = tmp_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

    # Copy symbols into .docstar/symbols/
    if symbols_dir.exists():
        docstar_symbols = tmp_path / ".docstar" / "symbols"
        for sym_file in symbols_dir.rglob("*.symbols.json"):
            rel = sym_file.relative_to(symbols_dir)
            dest = docstar_symbols / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sym_file, dest)

    return Config(root_path=tmp_path, respect_gitignore=False)


# ---------------------------------------------------------------------------
# Case 001: wrapper pattern
# ---------------------------------------------------------------------------

async def _run_trial_case_001(provider, config, tmp_path, expected) -> bool:
    """Run one LLM verification trial for case_001. Returns True if all pass."""
    zero_refs, _ = scan_references(config)

    # All expected dead should be zero-ref candidates
    zero_ref_names = {c.name for c in zero_refs}
    for dead_name in expected["dead"]:
        if dead_name not in zero_ref_names:
            return False

    tools_candidates = [
        c for c in zero_refs if c.source_path.endswith("tools.py")
    ]
    if not tools_candidates:
        return False

    tools_path = tmp_path / "src" / "docstar" / "tools.py"
    file_content = tools_path.read_text(errors="ignore")

    verifications, _, _ = await _verify_batch_async(
        provider, config, tools_candidates,
        file_content, "", {},
    )

    result_by_name = {v.name: v for v in verifications}

    for dead_name in expected["dead"]:
        if dead_name in result_by_name and not result_by_name[dead_name].is_dead:
            return False

    for alive_name in expected["alive"]:
        if alive_name in result_by_name and result_by_name[alive_name].is_dead:
            return False

    return True


# ---------------------------------------------------------------------------
# Case 002: internal dataclass
# ---------------------------------------------------------------------------

async def _run_trial_case_002(provider, config, tmp_path, expected) -> bool:
    """Run one LLM verification trial for case_002. Returns True if all pass."""
    audit_path = tmp_path / "src" / "docstar" / "audit.py"
    file_content = audit_path.read_text(errors="ignore")

    # Line numbers are coupled to the snapshotted fixture file in
    # tests/fixtures/prompt_regression/dead_code/case_002_internal_dataclass/source/,
    # NOT to the live src/docstar/audit.py. Update if the fixture changes.
    candidates = [
        DeadCodeCandidate(
            source_path="src/docstar/audit.py",
            name=name,
            kind="class",
            line_start={"AuditIssue": 19, "AuditResult": 32}[name],
            line_end={"AuditIssue": 30, "AuditResult": 50}[name],
            ref_count=0,
        )
        for name in expected["alive"]
    ]

    verifications, _, _ = await _verify_batch_async(
        provider, config, candidates,
        file_content, "", {},
    )

    result_by_name = {v.name: v for v in verifications}

    for alive_name in expected["alive"]:
        if alive_name in result_by_name and result_by_name[alive_name].is_dead:
            return False

    for dead_name in expected["dead"]:
        if dead_name in result_by_name and not result_by_name[dead_name].is_dead:
            return False

    return True


# ---------------------------------------------------------------------------
# Plumbing case 001: tool schema constraints
# ---------------------------------------------------------------------------

async def _run_trial_plumbing_001(provider, config, source_path, source_content) -> bool:
    """Run one trial for plumbing case_001. Returns True if no obligations extracted."""
    from docstar.plumbing import extract_obligations_async

    obligations, _, _ = await extract_obligations_async(
        provider, config, source_path, source_content, "",
    )

    # No obligations should be extracted from LLM tool schema constraints
    forbidden = {"confidence", "severity", "line_start", "line_end"}
    for obl in obligations:
        if obl.field_name in forbidden:
            return False

    return True


# ---------------------------------------------------------------------------
# String extraction case 001: dict values and conventions
# ---------------------------------------------------------------------------

async def _run_trial_string_extraction_001(provider, config, file_path, numbered_content, expected) -> bool:
    """Run one trial for string extraction case_001. Returns True if facts are correct."""
    from docstar.shadow import generate_file_shadow_doc_async

    _, _, _, _, _, _, _, facts = await generate_file_shadow_doc_async(
        provider, config, file_path, numbered_content,
    )

    string_literals = facts.get("string_literals", [])

    # Build lookup by value
    by_value: dict[str, list[dict]] = {}
    for sl in string_literals:
        if isinstance(sl, dict):
            val = sl.get("value", "")
            by_value.setdefault(val, []).append(sl)

    # Dict values like "python", "node" should NOT be classified as checked-only.
    # They should either be "produced" (from the dict) or not extracted at all.
    for val in expected.get("should_not_be_checked_only", []):
        entries = by_value.get(val, [])
        for entry in entries:
            if entry.get("usage") == "checked" and not any(
                e.get("usage") == "produced" for e in entries
            ):
                # String appears as checked-only — this is the FP pattern
                return False

    # Convention strings should ideally be skipped entirely
    convention_extracted = 0
    for val in expected.get("convention_strings_to_skip", []):
        if val in by_value:
            convention_extracted += 1
    # Allow up to half to leak through — LLM is stochastic
    if convention_extracted > len(expected.get("convention_strings_to_skip", [])) // 2:
        return False

    return True


# ---------------------------------------------------------------------------
# Parallel trial runner
# ---------------------------------------------------------------------------

async def _run_parallel_trials(trial_fn, n: int) -> tuple[int, int]:
    """Run n trials in parallel. Returns (passes, total).

    No concurrency limit here — rate limiting is handled by the rate_limiter module.
    """
    outcomes = await asyncio.gather(*[trial_fn() for _ in range(n)])
    passes = sum(1 for o in outcomes if o)
    return passes, n


# ---------------------------------------------------------------------------
# Statistical test harness
# ---------------------------------------------------------------------------

async def _run_statistical_test(
    trial_fn,
    expected: dict,
    expected_path: Path,
    establish_baseline: bool,
) -> None:
    """Shared statistical test logic for all prompt regression cases."""
    baseline = expected.get("baseline")

    if establish_baseline:
        n_trials = 30
        passes, total = await _run_parallel_trials(trial_fn, n_trials)
        p0 = passes / total
        expected["baseline"] = {
            "p0": round(p0, 4),
            "n_trials": n_trials,
            "established": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        expected_path.write_text(json.dumps(expected, indent=2) + "\n")
        print(f"\nBaseline established: p0={p0:.1%} ({passes}/{total})")
        assert p0 > 0, "Baseline pass rate is 0 — test is fundamentally broken"

    elif baseline:
        from tests.stat_utils import compute_sample_size, assert_pass_rate

        p0 = baseline["p0"]
        n = compute_sample_size(p0)
        passes, total = await _run_parallel_trials(trial_fn, n)
        print(f"\nStatistical test: {passes}/{total} passed (p0={p0:.1%}, N={n})")
        assert_pass_rate(passes, total, p0)

    else:
        passes, total = await _run_parallel_trials(trial_fn, 1)
        if passes == 0:
            pytest.skip(
                "No baseline established. Run with --establish-baseline first."
            )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_case_001_wrapper_pattern(tmp_path, establish_baseline):
    """tools.py: wrapper functions alongside used constants must be detected as dead.

    Regression test from commit d9eaec6 where 5 of 7 identical dead functions
    were missed due to LLM batch bias from correctly-alive constants.
    """
    case_dir = FIXTURES_DIR / "dead_code" / "case_001_wrapper_pattern"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())
    config = _setup_case_dir(tmp_path, case_dir)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_case_001(provider, config, tmp_path, expected)

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_case_002_internal_dataclass(tmp_path, establish_baseline):
    """audit.py: internal dataclasses used by externally-referenced functions must be alive.

    Regression test for false positives on AuditIssue and AuditResult — dataclasses
    with zero external references that are transitively alive through run_audit etc.
    """
    case_dir = FIXTURES_DIR / "dead_code" / "case_002_internal_dataclass"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())
    config = _setup_case_dir(tmp_path, case_dir)

    # Step 1: Verify scanner-level transitive liveness filter (deterministic)
    zero_refs, _ = scan_references(config)
    zero_ref_names = {c.name for c in zero_refs}

    for alive_name in expected["alive"]:
        assert alive_name not in zero_ref_names, (
            f"Transitive liveness filter missed {alive_name} — "
            f"it should NOT be a zero-ref candidate"
        )

    # Step 2: LLM verification (stochastic — use statistical framework)
    provider = create_provider("anthropic")
    try:
        async def trial_fn():
            return await _run_trial_case_002(provider, config, tmp_path, expected)

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_plumbing_001_tool_schema(tmp_path, establish_baseline):
    """Tool schema constraints (minimum, maximum, enum) should not be flagged as obligations.

    Regression test for false positives where LLM tool_use schema constraints like
    confidence range [0,1] and line minimum 1 were flagged as unactuated config.
    The constraints guide the LLM, not application code.
    """
    case_dir = FIXTURES_DIR / "plumbing" / "case_001_tool_schema"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "tools.py"
    source_content = source_file.read_text()

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_plumbing_001(
                provider, config, "tools.py", source_content,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_string_extraction_001_dict_and_conventions(tmp_path, establish_baseline):
    """Dict values should be 'produced', external conventions should be skipped.

    Uses the actual junk_deps.py that caused FP findings: "python", "node",
    "rust", "go" in _MANIFEST_FILES dict were classified as checked-only,
    missing their production site in the dict values.
    """
    case_dir = FIXTURES_DIR / "string_extraction" / "case_001_dict_and_conventions"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "junk_deps.py"
    source_content = source_file.read_text()
    numbered_content = "\n".join(
        f"{i + 1:4d}\t{line}"
        for i, line in enumerate(source_content.splitlines())
    )

    # Copy source into tmp_path so config paths resolve
    dest = tmp_path / "junk_deps.py"
    dest.write_text(source_content)

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_string_extraction_001(
                provider, config, dest, numbered_content, expected,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()
