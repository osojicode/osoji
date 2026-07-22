# tests\test_prompt_regression.py
@source-hash: de647b651ef9f698
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:48Z

## Purpose
Prompt regression test suite for the osoji project. Verifies that LLM prompt changes don't regress on known edge cases using snapshotted fixture files. Tests use real Anthropic API calls, are gated behind the `prompt_regression` pytest marker, and employ a statistical binomial test framework for stochastic LLM outputs.

## Architecture

### Test Categories
1. **Dead Code** (`dead_code/case_*`): Tests LLM triage of zero-reference symbols
2. **Dead Params** (`dead_params/case_*`): Tests dead parameter detection
3. **Plumbing** (`plumbing/case_*`): Tests obligation extraction from source files
4. **Latent Bug** (`latent_bug/case_*`): Tests latent bug finding generation via shadow doc

### Statistical Test Framework (L234–L271)
- `--establish-baseline`: Runs 30 trials, computes `p0`, writes to `expected.json["baseline"]`
- Default mode: Loads stored `p0`, calls `compute_sample_size(p0)` for N, runs N parallel trials, uses binomial test via `assert_pass_rate`
- No-baseline fallback: Runs 1 trial; skips if it fails (L265–L271)
- All trials run concurrently via `asyncio.gather` (L225)

## Key Functions

### Infrastructure Helpers
- `_setup_case_dir(tmp_path, case_dir) -> Config` (L60–92): Copies source/symbols/facts fixture dirs into temp project dir, returns `Config(root_path=tmp_path, respect_gitignore=False)`. Handles `.osoji/symbols/` and `.osoji/facts/` subdirectories.
- `_decide_candidates(provider, config, findings) -> dict` (L47–57): Async helper mimicking production Phase 4. Builds claims via `build_junk_claims`, decides via `decide_junk_claims`, returns `{symbol: Finding}` dict.
- `_run_parallel_trials(trial_fn, n) -> tuple[int, int]` (L220–227): Gathers n async `trial_fn()` calls concurrently, returns `(passes, total)`.
- `_run_statistical_test(trial_fn, expected, expected_path, establish_baseline)` (L234–271): Central statistical harness shared by all prompt regression tests.

### Trial Functions (return `bool` — True = pass)
- `_run_trial_case_001` (L126–155): Dead code / wrapper pattern. Scans references, filters `tools.py` candidates, runs LLM triage, checks `expected["dead"]` are confirmed and `expected["alive"]` are not.
- `_run_trial_case_002` (L162–192): Internal dataclass. Constructs hardcoded `DeadCodeCandidate` objects with fixed line numbers from fixture (L168–176). Checks transitive liveness — alive names must NOT get `verdict == "confirmed"`.
- `_run_trial_plumbing_001` (L199–213): Obligation extraction. Ensures fields `{"confidence", "severity", "line_start", "line_end"}` (L208) are not extracted as obligations.
- `_run_trial_dead_params_001` (L374–423): Dead parameter backward-compat. Scans, finds `build_scorecard` batch, fetches importers from `FactsDB`, creates findings, checks verdict against `expected["dead"]`/`expected["alive"]`.
- `_run_trial_latent_bug_002` (L457–470): Non-null assertion. Calls `generate_file_shadow_doc_async`, asserts no `latent_bug` findings produced.
- `_run_trial_latent_bug_003` (L477–490): Discriminated union narrowing. Same pattern as 002 — no `latent_bug` findings expected.
- `_run_trial_latent_bug_004` (L497–523): Hooks after conditional return (true positive). Checks that findings matching `expected["expected_findings"]` ARE produced, matching by `category`, `severity`, `description_contains`.

### Pytest Tests (all `@pytest.mark.prompt_regression @pytest.mark.asyncio`)
- `test_dead_params_002_high_fanout_fixture_limits_callers` (L95–109): **Deterministic** (no LLM). Asserts `candidate.call_sites` file paths match `expected["call_site_files"]`.
- `test_plumbing_002_doc_json_fixture_stays_doc_only` (L112–119): **Deterministic** (no LLM). Asserts `config.is_doc_candidate()` and `load_files_by_role` results.
- `test_case_001_wrapper_pattern` (L279–299): LLM statistical test, provider="anthropic".
- `test_case_002_internal_dataclass` (L304–335): Two-step: deterministic scanner check (L316–323), then LLM statistical test.
- `test_plumbing_001_tool_schema` (L340–367): LLM statistical test. Uses `extract_obligations_async` directly (no `_setup_case_dir`).
- `test_dead_params_001_backward_compat` (L428–449): LLM statistical test.
- `test_latent_bug_002_nonnull_assertion` (L533–566): LLM statistical test with line-numbered content.
- `test_latent_bug_003_discriminated_union` (L571–604): LLM statistical test.
- `test_latent_bug_004_hooks_after_conditional_return` (L609–643): LLM statistical true-positive test.
- `test_corpus_evaluate` (L654–729): `@pytest.mark.corpus_evaluate` opt-in. Replays full accepted corpus via `eval_lib`. Checks per-case record counts, schema round-trip, and `evaluate-baseline.json` thresholds.

## Path Constants
- `FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompt_regression"` (L35)
- `REPO_ROOT` (L40): Used to inject `scripts/` into `sys.path` for `eval_lib` import.

## Important Dependencies
- `osoji.config.Config`: Project config with `root_path` and `respect_gitignore`
- `osoji.deadcode.scan_references`, `DeadCodeCandidate`
- `osoji.deadparam.scan_dead_param_candidates`, `DeadParamCandidate`
- `osoji.evidence_builders.BuildContext`
- `osoji.findings_adapter.finding_from_dead_code_candidate`, `finding_from_dead_param_candidate`
- `osoji.junk_triage.build_junk_claims`, `decide_junk_claims`
- `osoji.llm.factory.create_provider` — always called with `"anthropic"`
- `osoji.symbols.load_files_by_role`
- `osoji.plumbing.extract_obligations_async` (lazy import, L201)
- `osoji.shadow.generate_file_shadow_doc_async` (lazy import, L459, L479, L499)
- `osoji.facts.FactsDB` (lazy import, L376)
- `eval_lib` (scripts/ module, L44): `load_corpus`, `resolve_variant`, `evaluate_corpus`, `write_verdict_ndjson`, `read_verdict_ndjson`, `check_thresholds`, `CORPUS_ROOT`, `VERDICT_SCHEMA`
- `tests.stat_utils.compute_sample_size`, `assert_pass_rate` (lazy import, L257–258)

## Notable Patterns
- All LLM provider instances are created and closed in `try/finally` blocks (e.g., L291–299)
- `generate_file_shadow_doc_async` returns 8-tuple; index 3 is `findings` (L461, L481, L501)
- Fixture line numbers for `case_002` are hardcoded and coupled to the snapshot file (L164–176)
- `_run_trial_dead_params_001` strips function name prefix with `rsplit(".", 1)[-1]` (L409) to match bare param names against `expected`
- `numbered_content` format: `f"{i + 1:4d}\t{line}"` (L545–548, L583–586, L621–624)
- `test_corpus_evaluate` never fires in default CI — requires `--evaluate` flag; skips before provider construction if corpus empty (L666–671)