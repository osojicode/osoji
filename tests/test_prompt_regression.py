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
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from osoji.config import Config
from osoji.deadcode import DeadCodeCandidate, scan_references
from osoji.deadparam import DeadParamCandidate, scan_dead_param_candidates
from osoji.evidence_builders import BuildContext
from osoji.findings_adapter import (
    finding_from_dead_code_candidate,
    finding_from_dead_param_candidate,
)
from osoji.junk_triage import build_junk_claims, decide_junk_claims
from osoji.llm.factory import create_provider
from osoji.symbols import load_files_by_role

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompt_regression"

# scripts/eval_lib.py (V1-7 corpus evaluator, osojicode/work#35) backs test_corpus_evaluate
# below — it isn't installed as a package, so it needs scripts/ on sys.path the
# same way scripts/corpus_replay.py and tests/test_eval_lib.py already do.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_lib  # noqa: E402


async def _decide_candidates(provider, config, findings) -> dict:
    """Build claims and decide them exactly as production Phase 4 does (V1-5a).

    Returns decided Findings keyed by ``symbol``.
    """
    ctx = BuildContext(config)
    claims = build_junk_claims(findings, ctx)
    decided, _in_tokens, _out_tokens = await decide_junk_claims(
        claims, config, provider,
    )
    return {f.symbol: f for f in decided}


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

    findings = [finding_from_dead_code_candidate(c) for c in tools_candidates]
    result_by_name = await _decide_candidates(provider, config, findings)

    for dead_name in expected["dead"]:
        finding = result_by_name.get(dead_name)
        if finding is not None and finding.verdict != "confirmed":
            return False

    for alive_name in expected["alive"]:
        finding = result_by_name.get(alive_name)
        if finding is not None and finding.verdict == "confirmed":
            return False

    return True


# ---------------------------------------------------------------------------
# Case 002: internal dataclass
# ---------------------------------------------------------------------------

async def _run_trial_case_002(provider, config, tmp_path, expected) -> bool:
    """Run one LLM verification trial for case_002. Returns True if all pass."""
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

    findings = [finding_from_dead_code_candidate(c) for c in candidates]
    result_by_name = await _decide_candidates(provider, config, findings)

    for alive_name in expected["alive"]:
        finding = result_by_name.get(alive_name)
        if finding is not None and finding.verdict == "confirmed":
            return False

    for dead_name in expected["dead"]:
        finding = result_by_name.get(dead_name)
        if finding is not None and finding.verdict != "confirmed":
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
    from osoji.facts import FactsDB

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

    facts_db = FactsDB(config)
    importers = sorted(
        facts_db.importers_of(scorecard_batch[0].source_path.replace("\\", "/"))
    )
    findings = [
        finding_from_dead_param_candidate(c, importers=importers)
        for c in scorecard_batch
    ]
    decided_by_symbol = await _decide_candidates(provider, config, findings)
    # Findings are keyed by "function.param"; expected names are bare params.
    result_by_name = {
        symbol.rsplit(".", 1)[-1]: finding
        for symbol, finding in decided_by_symbol.items()
    }

    for dead_name in expected["dead"]:
        finding = result_by_name.get(dead_name)
        if finding is not None and finding.verdict != "confirmed":
            return False

    for alive_name in expected["alive"]:
        finding = result_by_name.get(alive_name)
        if finding is not None and finding.verdict == "confirmed":
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
# Latent bug case 002: non-null assertion
# ---------------------------------------------------------------------------

async def _run_trial_latent_bug_002(provider, config, file_path, numbered_content) -> bool:
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

async def _run_trial_latent_bug_003(provider, config, file_path, numbered_content) -> bool:
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
                provider, config, dest, numbered_content,
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
                provider, config, dest, numbered_content,
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


# ---------------------------------------------------------------------------
# Corpus evaluator (V1-7, osojicode/work#35): pytest --evaluate mode
# ---------------------------------------------------------------------------


@pytest.mark.prompt_regression
@pytest.mark.corpus_evaluate
@pytest.mark.asyncio
async def test_corpus_evaluate(tmp_path, evaluate_mode, evaluate_out):
    """Replay the full accepted corpus through Triage; gate against a pinned baseline.

    Opt-in only: ``pytest tests/test_prompt_regression.py --evaluate`` (see
    conftest.py's ``--evaluate``/``--evaluate-out`` options and the
    collection hook that deselects every OTHER test in this file once
    --evaluate is passed, so this is the only thing that runs). Spends real
    LLM tokens against the whole corpus in one variant/one repeat — never
    fires in the default suite or in CI, and skips before any provider is
    constructed when the corpus is empty or --evaluate wasn't
    passed, so it needs no API key in either of those cases.
    """
    if not evaluate_mode:
        pytest.skip("pass --evaluate to run the corpus evaluator (opt-in, live LLM calls)")

    cases = eval_lib.load_corpus()
    if not cases:
        pytest.skip("corpus empty")

    variant = eval_lib.resolve_variant("baseline=@default")
    provider = create_provider("anthropic")
    try:
        run = await eval_lib.evaluate_corpus(
            cases,
            [variant],
            repeats=1,
            provider=provider,
            workdir=tmp_path / "work",
            corpus_root=eval_lib.CORPUS_ROOT,
        )
    finally:
        await provider.close()

    # Every selected case produced exactly `repeats` (1) record.
    counts: dict[str, int] = {}
    for record in run.records:
        counts[record["case"]] = counts.get(record["case"], 0) + 1
    for case in cases:
        assert counts.get(case.key, 0) == 1, (
            f"expected exactly 1 record for {case.key!r}, got {counts.get(case.key, 0)}"
        )

    assert run.run_meta.get("schema") == eval_lib.VERDICT_SCHEMA
    assert run.run_meta.get("record") == "run_meta"

    out_path = evaluate_out / f"{run.run_meta['run_id']}.ndjson"
    eval_lib.write_verdict_ndjson(run.records, run.run_meta, out_path)

    # Trailer-last, schema-valid round trip of the WRITTEN file
    # (read_verdict_ndjson raises if the last line isn't a valid run_meta trailer).
    read_records, read_meta = eval_lib.read_verdict_ndjson(out_path)
    assert read_meta["record"] == "run_meta"
    assert len(read_records) == len(run.records)

    metrics = run.run_meta["metrics"]
    print(f"\ncorpus evaluate: run_id={run.run_meta['run_id']} n_cases={metrics['n_cases']}")
    print(f"{'detector':<40s}{'tp_rate':>10s}{'fp_rate':>10s}")
    detectors = sorted(set(metrics["tp_rate_by_detector"]) | set(metrics["fp_rate_by_detector"]))
    for detector in detectors:
        tp = metrics["tp_rate_by_detector"].get(detector, 0.0)
        fp = metrics["fp_rate_by_detector"].get(detector, 0.0)
        print(f"{detector:<40s}{tp:>10.1%}{fp:>10.1%}")
    print(
        f"overall: tp_rate={metrics['tp_rate']:.1%} fp_rate={metrics['fp_rate']:.1%} "
        f"accuracy_nongray={metrics['accuracy_nongray']:.1%} "
        f"ce_gap_gap_type={metrics['ce_gap_gap_type']:.1%} me_overlap={metrics['me_overlap']:.1%} "
        f"uncertain_rate={metrics['uncertain_rate']:.1%} undecided_rate={metrics['undecided_rate']:.1%}"
    )

    baseline_path = eval_lib.CORPUS_ROOT / "evaluate-baseline.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        violations = eval_lib.check_thresholds(metrics, baseline)
        assert not violations, "evaluate-baseline.json threshold violations:\n" + "\n".join(
            violations
        )
    else:
        print("no evaluate-baseline.json; thresholds not enforced")
