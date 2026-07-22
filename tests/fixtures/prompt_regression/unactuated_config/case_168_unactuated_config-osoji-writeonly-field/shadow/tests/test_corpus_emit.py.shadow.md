# tests\test_corpus_emit.py
@source-hash: 6f8205d9e1c34689
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:33Z

## Purpose
Integration and unit test suite for `src/osoji/corpus_emit.py` — the `osoji corpus emit` CLI seam. Builds fabricated repos under `tmp_path`, exercises `emit_case`/`resolve_dest` directly, and performs round-trip validation through `eval_lib.load_corpus`/`stage_case` to confirm emitted corpus stubs are correctly shaped. Fully deterministic — no LLM calls, no network.

## File Layout

### Setup / Path Manipulation (L21–23)
Inserts both `scripts/` and `src/` onto `sys.path` so `eval_lib` and `osoji.*` are importable without installation. This is a common test harness pattern in this project.

### Fabrication Helpers

- **`_write(root, rel, content)` (L45–48)**: Creates a file at `root/rel`, making intermediate directories. Used pervasively throughout test setup.

- **`_make_finding(**overrides)` (L51–72)**: Constructs a `Finding` from a canonical base dict (`deadcode:dead_symbol` detector, `src/app/util.py` path, `unused_helper` symbol), merging any overrides. Returns a `Finding` instance. All optional Finding fields default to `None`.

- **`_build_repo(tmp_path)` (L75–128)**: Core fixture builder. Creates a fabricated repo containing:
  - `src/app/util.py`, `src/app/caller.py`, `README.md`
  - Two findings: `confirmed` (verdict=`"confirmed"`, has cross_file_reference evidence pointing at `caller.py`) and `uncertain` (verdict=`"uncertain"`)
  - Ledger at `.osoji/analysis/decided-findings.json` with schema `"decided-findings/1"`
  - Sidecars only for `util.py`: `.osoji/symbols/`, `.osoji/facts/`, `.osoji/shadow/`
  - Returns `(repo: Path, confirmed: Finding, uncertain: Finding)`

## Test Groups

### `emit_case` Happy Path (L136–205)

- **`test_emit_case_creates_full_stub_layout` (L136–194)**: Most comprehensive test. Verifies:
  - `case_dir` resolves to `dest/dead_symbol/case_unused-helper`
  - `source/` contains exactly `caller.py` and `util.py` (flagged file + evidence-referenced file)
  - Sidecars for `util.py` copied; `caller.py` sidecars absent
  - `case.json` schema, slug, category, detector, gap_type, language, snapshot_ref, evidence_policy, origin fields
  - `finding.json` path (no backslashes), symbol, id; verdict/confidence/etc stripped to `None`; evidence = `[]`
  - `expected.json` schema, verdict, reasoning, gray=False, adjudicated_by=`"sweep-proposed"`, accepted=False

- **`test_emit_case_language_default_and_override` (L197–205)**: Defaults to `"python"` for `.py` files; `language` param overrides.

- **`test_emit_case_include_adds_extra_file` (L208–215)**: `include=["docs/notes.md"]` copies an extra file into `source/`.

- **`test_emit_case_reasoning_and_gray_overrides_win` (L218–229)**: `reasoning` and `gray=True` kwargs override ledger triage_reasoning and default gray.

- **`test_emit_case_expected_verdict_override_wins_over_decided` (L232–239)**: `expected_verdict="dismissed"` overrides ledger's `"confirmed"`.

### `emit_case` Error Cases (L247–412)

- **`test_emit_case_missing_ledger_raises_clear_error` (L247–253)**: No ledger → `CorpusEmitError` matching `"osoji audit"`.

- **`test_emit_case_missing_id_raises_with_near_miss_listing` (L256–268)**: Unknown ID → error message includes the bad ID, both findings' paths, and both findings' IDs. No partial directory written.

- **`test_emit_case_uncertain_verdict_requires_expected_verdict_override` (L271–283)**: `uncertain` verdict without `expected_verdict` → `CorpusEmitError` matching `"expected-verdict"`. With `expected_verdict="dismissed"`, succeeds.

- **`test_emit_case_bad_slug_raises` (L286–291)**: Invalid slug (`"Not A Valid Slug!"`) → `CorpusEmitError` matching `"slug"`.

- **`test_emit_case_include_nonexistent_file_raises` (L294–301)**: Nonexistent include file → `CorpusEmitError` matching `"does not exist"`. No partial dir.

- **`test_emit_case_duplicate_dir_raises` (L304–311)**: Second `emit_case` with same slug → `CorpusEmitError` matching `"already exists"`.

- **`test_emit_case_file_cap_exceeded_raises` (L314–347)**: `MAX_FILES + 5` referenced files → `CorpusEmitError` matching `"exceeds the corpus-emit cap"`. Message must not suggest `"--include"`, must include `"too many files"` or `"targeted evidence"`. No partial dir. Also validates the inline comment at L339–345 about `--include` being additive-only.

- **`test_emit_case_missing_finding_path_file_names_no_such_file` (L350–366)**: Flagged file deleted after audit → `CorpusEmitError` matching `"no such file"` (not `"outside the repo"`). Pre-flight validation ensures no partial dir is created.

- **`test_emit_case_finding_path_escaping_repo_raises` (L369–383)**: Path `"../outside.py"` in ledger → `CorpusEmitError` matching `"outside the repo"` (not `"no such file"`). No partial dir.

- **`test_emit_case_mid_copy_failure_removes_partial_case_dir` (L386–412)**: Monkeypatches `corpus_emit_module.shutil.copy2` to fail on second call. Verifies cleanup-on-failure removes `case_dir` even after the first file was copied.

### `_category_of` Parametrized Tests (L421–461)

- **`test_category_of_derives_category_from_detector_suffix` (L460–461)**: 18 parametrized cases verifying `_category_of(detector)` extracts the suffix correctly:
  - `deadcode:dead_symbol` → `dead_symbol`
  - `doc:stale_content` → `doc_stale_content` (doc prefix prepended)
  - `debris:dead_code` → `dead_code` (legacy vocabulary round-trips as-is)
  - obligations already arrive `obligation_`-prefixed

### `resolve_dest` Tests (L469–492)

- **`test_resolve_dest_prefers_explicit_override` (L469–470)**: Explicit `dest` argument takes priority.
- **`test_resolve_dest_uses_env_var` (L473–476)**: `ENV_CORPUS_DEST` env var used when no explicit dest.
- **`test_resolve_dest_defaults_to_holding_when_corpus_present` (L479–485)**: Falls back to `tests/fixtures/prompt_regression/_holding` when that directory exists in the repo.
- **`test_resolve_dest_raises_when_nothing_resolves` (L488–492)**: No dest, no env var, no corpus dir → `CorpusEmitError` mentioning `ENV_CORPUS_DEST`.

### Integration Round-Trip (L500–532)

- **`test_emitted_case_loads_and_stages_after_acceptance` (L500–532)**: Full acceptance flow:
  1. `emit_case` → emits stub to `_holding`
  2. Flips `expected["accepted"] = True`, writes back
  3. `shutil.move` simulates `git mv` to `corpus_root/dead_symbol/case_101_accepted-case`
  4. `load_corpus(corpus_root)` → returns 1 case with correct key, symbol, expected verdict
  5. `stage_case(case, workdir)` → verifies source files and sidecars copied under `config.root_path`

### CLI Tests (L540–591)

- **`test_cli_corpus_emit_help` (L540–547)**: `--help` exits 0, outputs `--id` and `--slug`.
- **`test_cli_corpus_emit_bad_slug_errors` (L550–561)**: Bad slug → non-zero exit, `"slug"` in output.
- **`test_cli_corpus_emit_missing_dest_resolution_errors` (L564–576)**: No dest/env var → non-zero exit, `ENV_CORPUS_DEST` in output.
- **`test_cli_corpus_emit_creates_case_and_prints_reminder` (L579–591)**: Successful emit → exit 0, `"git mv"` in output, `case.json` exists.

## Key Imports and Dependencies
- `osoji.corpus_emit`: `ENV_CORPUS_DEST`, `MAX_FILES`, `CorpusEmitError`, `_category_of`, `emit_case`, `resolve_dest`
- `osoji.cli`: `main` (Click CLI entry point)
- `osoji.evidence`: `Evidence`
- `osoji.findings`: `Finding`
- `eval_lib`: `load_corpus`, `stage_case` (from `scripts/`)
- `click.testing.CliRunner`: For CLI invocation without subprocess

## Notable Patterns
- **Pre-flight validation architecture**: Multiple tests verify that validation occurs before `case_dir` is created, ensuring no partial directories on error.
- **Ledger manipulation**: Several error-case tests directly mutate the ledger JSON on disk to simulate edge cases (escaped paths, extra findings).
- **Monkeypatch of `shutil.copy2`**: Accessed via `corpus_emit_module.shutil.copy2` (attribute on module, not imported name) — important for the patch to take effect.
- **Evidence-driven file collection**: `confirmed` finding's `cross_file_reference` evidence drives which files appear in `source/`.
- **Accepted flag in expected.json**: `load_corpus` only loads cases where `accepted=True`; the integration test simulates the full acceptance workflow.