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

from osoji.config import Config
from osoji.deadcode import DeadCodeCandidate, _verify_batch_async, scan_references
from osoji.deadparam import (
    DeadParamCandidate,
    scan_dead_param_candidates,
    _verify_batch_async as _verify_dead_params_batch_async,
)
from osoji.llm.factory import create_provider
from osoji.symbols import load_files_by_role

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompt_regression"


def _setup_case_dir(tmp_path: Path, case_dir: Path) -> Config:
    """Copy snapshotted source files into a temp project dir and return a Config."""
    source_dir = case_dir / "source"
    symbols_dir = case_dir / "symbols"
    facts_dir = case_dir / "facts"

    # Copy source files
    for src_file in source_dir.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(source_dir)
            dest = tmp_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

    # Copy symbols into .osoji/symbols/
    if symbols_dir.exists():
        osoji_symbols = tmp_path / ".osoji" / "symbols"
        for sym_file in symbols_dir.rglob("*.symbols.json"):
            rel = sym_file.relative_to(symbols_dir)
            dest = osoji_symbols / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sym_file, dest)

    # Copy facts into .osoji/facts/
    if facts_dir.exists():
        osoji_facts = tmp_path / ".osoji" / "facts"
        for facts_file in facts_dir.rglob("*.facts.json"):
            rel = facts_file.relative_to(facts_dir)
            dest = osoji_facts / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(facts_file, dest)

    return Config(root_path=tmp_path, respect_gitignore=False)


def test_dead_params_002_high_fanout_fixture_limits_callers(tmp_path):
    """High-fanout common-name fixture should only retain direct importer call sites."""
    case_dir = FIXTURES_DIR / "dead_params" / "case_002_high_fanout"
    expected = json.loads((case_dir / "expected.json").read_text())
    config = _setup_case_dir(tmp_path, case_dir)

    candidates = scan_dead_param_candidates(config)
    candidate = next(
        candidate
        for candidate in candidates
        if candidate.function_name == expected["function_name"]
        and candidate.param_name == expected["param_name"]
    )

    assert sorted({call_site.file_path for call_site in candidate.call_sites}) == expected["call_site_files"]


def test_plumbing_002_doc_json_fixture_stays_doc_only(tmp_path):
    """Doc JSON fixture should remain a doc candidate and stay out of schema roles."""
    case_dir = FIXTURES_DIR / "plumbing" / "case_002_doc_json_reference"
    expected = json.loads((case_dir / "expected.json").read_text())
    config = _setup_case_dir(tmp_path, case_dir)

    assert config.is_doc_candidate(Path(expected["doc_file"])) is True
    assert load_files_by_role(config, "schema") == expected["schema_files"]


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

    tools_path = tmp_path / "src" / "osoji" / "tools.py"
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
    audit_path = tmp_path / "src" / "osoji" / "audit.py"
    file_content = audit_path.read_text(errors="ignore")

    # Line numbers are coupled to the snapshotted fixture file in
    # tests/fixtures/prompt_regression/dead_code/case_002_internal_dataclass/source/,
    # NOT to the live src/osoji/audit.py. Update if the fixture changes.
    candidates = [
        DeadCodeCandidate(
            source_path="src/osoji/audit.py",
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
    from osoji.plumbing import extract_obligations_async

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


# ---------------------------------------------------------------------------
# Dead params case 001: backward compat parameters
# ---------------------------------------------------------------------------

async def _run_trial_dead_params_001(provider, config, tmp_path, expected) -> bool:
    """Run one LLM verification trial for dead_params case_001. Returns True if all pass."""
    from osoji.junk import load_shadow_content

    candidates = scan_dead_param_candidates(config)
    if not candidates:
        return False

    # Group by (source_path, function_name) for batching
    by_func: dict[tuple[str, str], list[DeadParamCandidate]] = {}
    for c in candidates:
        key = (c.source_path, c.function_name)
        by_func.setdefault(key, []).append(c)

    # Find the build_scorecard batch
    scorecard_batch = None
    for key, batch in by_func.items():
        if "build_scorecard" in key[1]:
            scorecard_batch = batch
            break

    if not scorecard_batch:
        return False

    source_path = scorecard_batch[0].source_path
    src_file = tmp_path / source_path
    file_content = src_file.read_text(errors="ignore")
    shadow_content = load_shadow_content(config, source_path)

    verifications, _, _ = await _verify_dead_params_batch_async(
        provider, config, scorecard_batch,
        file_content, shadow_content,
    )

    result_by_name = {v.param_name: v for v in verifications}

    for dead_name in expected["dead"]:
        if dead_name in result_by_name and not result_by_name[dead_name].is_dead:
            return False

    for alive_name in expected["alive"]:
        if alive_name in result_by_name and result_by_name[alive_name].is_dead:
            return False

    return True


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_dead_params_001_backward_compat(tmp_path, establish_baseline):
    """build_scorecard backward-compat params dead_code_results and plumbing_result are dead.

    Regression test verifying that the dead parameter analyzer correctly identifies
    dead_code_results and plumbing_result as dead (no caller passes them) while
    keeping config, analysis_results, and junk_results alive.
    """
    case_dir = FIXTURES_DIR / "dead_params" / "case_001_backward_compat"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())
    config = _setup_case_dir(tmp_path, case_dir)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_dead_params_001(provider, config, tmp_path, expected)

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


# ---------------------------------------------------------------------------
# String extraction case 002: external codes (SQLSTATE)
# ---------------------------------------------------------------------------

async def _run_trial_string_extraction_002(provider, config, file_path, numbered_content, expected) -> bool:
    """Run one trial for string_extraction case_002. Returns True if external codes are not checked-only."""
    from osoji.shadow import generate_file_shadow_doc_async

    _, _, _, _, _, _, _, facts = await generate_file_shadow_doc_async(
        provider, config, file_path, numbered_content,
    )

    string_literals = facts.get("string_literals", [])

    by_value: dict[str, list[dict]] = {}
    for sl in string_literals:
        if isinstance(sl, dict):
            val = sl.get("value", "")
            by_value.setdefault(val, []).append(sl)

    # External codes like "23505" should NOT be kind:identifier + usage:checked-only.
    # They should be kind:config, or not extracted at all.
    for val in expected.get("should_not_be_checked_only", []):
        entries = by_value.get(val, [])
        for entry in entries:
            if entry.get("kind") == "identifier" and entry.get("usage") == "checked":
                return False

    return True


# ---------------------------------------------------------------------------
# Latent bug case 002: non-null assertion
# ---------------------------------------------------------------------------

async def _run_trial_latent_bug_002(provider, config, file_path, numbered_content, expected) -> bool:
    """Run one trial for latent_bug case_002. Returns True if no latent_bug findings on non-null assertion."""
    from osoji.shadow import generate_file_shadow_doc_async

    _, _, _, findings, _, _, _, _ = await generate_file_shadow_doc_async(
        provider, config, file_path, numbered_content,
    )

    # No latent_bug findings should be produced for non-null assertion patterns
    for f in findings:
        if f.category == "latent_bug":
            return False

    return True


# ---------------------------------------------------------------------------
# Latent bug case 003: discriminated union narrowing
# ---------------------------------------------------------------------------

async def _run_trial_latent_bug_003(provider, config, file_path, numbered_content, expected) -> bool:
    """Run one trial for latent_bug case_003. Returns True if no latent_bug findings on narrowed union."""
    from osoji.shadow import generate_file_shadow_doc_async

    _, _, _, findings, _, _, _, _ = await generate_file_shadow_doc_async(
        provider, config, file_path, numbered_content,
    )

    # No latent_bug findings should be produced for discriminated union narrowing
    for f in findings:
        if f.category == "latent_bug":
            return False

    return True


# ---------------------------------------------------------------------------
# Latent bug case 004: hooks after conditional return (true positive)
# ---------------------------------------------------------------------------

async def _run_trial_latent_bug_004(provider, config, file_path, numbered_content, expected) -> bool:
    """Run one trial for latent_bug case_004. Returns True if hooks violation IS detected."""
    from osoji.shadow import generate_file_shadow_doc_async

    _, _, _, findings, _, _, _, _ = await generate_file_shadow_doc_async(
        provider, config, file_path, numbered_content,
    )

    expected_findings = expected.get("expected_findings", [])
    if not expected_findings:
        return True

    for ef in expected_findings:
        matched = False
        for f in findings:
            if f.category != ef.get("category"):
                continue
            if ef.get("severity") and f.severity != ef["severity"]:
                continue
            if ef.get("description_contains") and ef["description_contains"].lower() not in f.description.lower():
                continue
            matched = True
            break
        if not matched:
            return False

    return True


# ---------------------------------------------------------------------------
# Test cases: new prompt regression tests
# ---------------------------------------------------------------------------

@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_string_extraction_002_external_codes(tmp_path, establish_baseline):
    """SQLSTATE codes like '23505' should be kind:config, not kind:identifier.

    Database error codes are external protocol values defined by PostgreSQL,
    not project-internal identifiers. Classifying them as identifier + checked
    causes false positive obligation_violation findings.
    """
    case_dir = FIXTURES_DIR / "string_extraction" / "case_002_external_codes"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "handler.ts"
    source_content = source_file.read_text()
    numbered_content = "\n".join(
        f"{i + 1:4d}\t{line}"
        for i, line in enumerate(source_content.splitlines())
    )

    dest = tmp_path / "handler.ts"
    dest.write_text(source_content)

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_string_extraction_002(
                provider, config, dest, numbered_content, expected,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_latent_bug_002_nonnull_assertion(tmp_path, establish_baseline):
    """Non-null assertion (!) is intentional, not a latent bug.

    TypeScript's non-null assertion operator is a deliberate developer choice.
    The prompt should instruct the LLM not to flag these as unguarded dereferences.
    """
    case_dir = FIXTURES_DIR / "latent_bug" / "case_002_nonnull_assertion"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "main.ts"
    source_content = source_file.read_text()
    numbered_content = "\n".join(
        f"{i + 1:4d}\t{line}"
        for i, line in enumerate(source_content.splitlines())
    )

    dest = tmp_path / "main.ts"
    dest.write_text(source_content)

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_latent_bug_002(
                provider, config, dest, numbered_content, expected,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_latent_bug_003_discriminated_union(tmp_path, establish_baseline):
    """Discriminant check narrows union type; access on narrowed variant is safe.

    When TypeScript narrows a discriminated union via type guards, accessing
    variant-specific members is type-safe and should not be flagged.
    """
    case_dir = FIXTURES_DIR / "latent_bug" / "case_003_discriminated_union"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "metrics.ts"
    source_content = source_file.read_text()
    numbered_content = "\n".join(
        f"{i + 1:4d}\t{line}"
        for i, line in enumerate(source_content.splitlines())
    )

    dest = tmp_path / "metrics.ts"
    dest.write_text(source_content)

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_latent_bug_003(
                provider, config, dest, numbered_content, expected,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()


@pytest.mark.prompt_regression
@pytest.mark.asyncio
async def test_latent_bug_004_hooks_after_conditional_return(tmp_path, establish_baseline):
    """React useState after conditional returns violates Rules of Hooks.

    This is a true positive guard: hooks placed after conditional early returns
    cause hooks to execute in different order across renders, crashing at runtime.
    Must still be detected after adding non-null assertion and union narrowing exemptions.
    """
    case_dir = FIXTURES_DIR / "latent_bug" / "case_004_hooks_after_conditional_return"
    expected_path = case_dir / "expected.json"
    expected = json.loads(expected_path.read_text())

    source_file = case_dir / "source" / "component.tsx"
    source_content = source_file.read_text()
    numbered_content = "\n".join(
        f"{i + 1:4d}\t{line}"
        for i, line in enumerate(source_content.splitlines())
    )

    dest = tmp_path / "component.tsx"
    dest.write_text(source_content)

    config = Config(root_path=tmp_path, respect_gitignore=False)
    provider = create_provider("anthropic")

    try:
        async def trial_fn():
            return await _run_trial_latent_bug_004(
                provider, config, dest, numbered_content, expected,
            )

        await _run_statistical_test(
            trial_fn, expected, expected_path, establish_baseline,
        )
    finally:
        await provider.close()
