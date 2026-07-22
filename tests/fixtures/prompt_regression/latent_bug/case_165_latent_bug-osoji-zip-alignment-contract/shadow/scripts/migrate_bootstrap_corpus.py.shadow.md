# scripts\migrate_bootstrap_corpus.py
@source-hash: b8f271016b87ed00
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:58:44Z

## Purpose

One-time (but rerunnable), fully deterministic migration script that converts the 54-entry bootstrap manifest (`tests/fixtures/bootstrap/manifest.json`) into `corpus-case/1` format under `tests/fixtures/prompt_regression/_holding/`. Zero LLM calls. Two entry classes: **A (fixture-origin)** entries point at existing legacy fixture dirs via `snapshot_ref`; **B (audit-origin)** entries snapshot files via `git show <commit>:<path>` into a fresh `source/` tree and regenerate `facts/` sidecars via tree-sitter. `symbols/` and `shadow/` sidecars are intentionally skipped (require LLM). Every migrated case lands with `accepted: false`.

---

## Architecture

Two passes per invocation:
1. **Write pass** (L952–979): respects `--only`, may create case dirs.
2. **Report pass** (L982–1009): always re-validates the FULL manifest, never writes. Produces `MIGRATION-REPORT.md` and `MIGRATION-SKIPPED.md` as deterministic functions of on-disk state — byte-identical across reruns over an unchanged tree.

Each entry class has a paired validator (`_validate_*`) and status reporter (`_status_*`) that share no state with the write path. Validators are pure/read-only.

---

## Key Constants (L108–133)

- `REPO_ROOT` (L84): repo root derived from script location
- `BOOTSTRAP_DIR` (L108): `tests/fixtures/bootstrap`
- `DEFAULT_MANIFEST` (L109): `BOOTSTRAP_DIR/manifest.json`
- `CORPUS_ROOT` (L113): `tests/fixtures/prompt_regression`
- `CORPUS_ROOT_REL` (L114): POSIX string version of the above
- `DEFAULT_DEST` (L115): `CORPUS_ROOT/_holding`
- `FALLBACK_ADJUDICATED_AT` (L119): `"2026-07-03T00:00:00Z"` — used only if manifest lacks `audited`
- `ADJUDICATED_BY` (L120): `"bootstrap-manifest"`
- `SWEEP_RUN` (L121): `"bootstrap-manifest-migration"`
- `_TRIAGE_OUTPUT_FIELDS` (L125–133): tuple of 7 triage output field names nulled in `finding.json`

---

## Classes

### `MigrationOutcome` (L433–439)
Slot-based class (not dataclass) representing per-entry write-pass result.
- `status`: `"migrated"` | `"exists"` | `"skipped"`
- `reason`: optional string explanation
- `facts_written`: count of facts sidecar files written (B entries only)

### `_FixtureValidation` (L442–446, frozen dataclass)
Carries everything needed to write a fixture-origin case:
- `finding: Finding`
- `snapshot_ref: str` (relative path into corpus root)
- `stripped_path: str` (source-relative path for `finding.json`)

### `_AuditValidation` (L536–540, frozen dataclass)
Carries everything needed to write an audit-origin case:
- `finding: Finding`
- `finding_path: str` (POSIX path as seen in git)
- `relevant: frozenset[str]` (finding path + evidence paths)

---

## Key Functions

### Small Helpers (L141–270)

- `_iso_from_manifest_date(date_str)` (L141–146): Converts `"2026-07-01"` to `"2026-07-01T00:00:00Z"` or returns `FALLBACK_ADJUDICATED_AT`.
- `_adjudicated_reasoning(entry)` (L149–168): Combines `adjudication_notes` + optional `adjudication_reasoning` (append, never replace) to avoid coherent verdict/reasoning mismatches for re-adjudicated entries.
- `_load_finding_or_none(finding_blob)` (L171–182): `Finding.from_dict` + round-trip check; returns `(None, reason)` on failure.
- `_finding_for_case(finding, *, path)` (L185–196): Returns a corpus `finding.json` shape with triage outputs nulled, evidence cleared, path rewritten to snapshot-relative.
- `_build_case_json(...)` (L199–226): Constructs `case.json` dict. Calls `_git(["remote", "get-url", "origin"], REPO_ROOT)` for the remote URL.
- `_build_expected_json(entry, adjudicated_at)` (L229–240): Constructs `expected.json` with `accepted: false`.
- `_case_dir_for(dest, entry)` (L243–244): Returns `dest/<category>/case_<slug>`.
- `_case_already_handled(entry, dest)` (L247–270): Returns `True` if case dir exists in `dest` OR if the entry was already accepted into the live corpus (glob for `case_*_<slug>` in `CORPUS_ROOT/<category>/`). Prevents silently resurrecting accepted cases on rerun.

### Git Snapshot Helpers (L278–356)

- `_git_show_exists(commit, path)` (L278–284): Runs `git cat-file -e <commit>:<path>`, returns bool.
- `_git_show_bytes(commit, path)` (L287–295): Runs `git show <commit>:<path>`, returns bytes or None.
- `_normalize_snapshot_bytes(data)` (L298–321): Normalizes CRLF/CR → LF for UTF-8-decodable content before hashing/writing; passes binary through unchanged.
- `_safe_relative_posix(raw)` (L324–334): POSIX-normalizes a path; returns None for absolute paths or `..` traversal attempts.
- `_evidence_paths_at_commit(finding_blob, commit)` (L337–356): Walks `finding["evidence"]` payload strings, returns set of repo-relative paths that exist at `commit` via `git cat-file`. Currently a no-op (evidence is `[]` in all manifest entries).

### Facts Sidecar Regeneration (L365–407)

- `_write_facts_sidecars(case_dir, source_root, generated_at)` (L365–407): For every `.py` under `source_root`, runs `PythonPlugin.extract_project_facts`, writes `facts/<relpath>.facts.json` with `extraction_method: "ast"`. Returns list of relative paths written. Silently returns `[]` if plugin unavailable or no Python files.

### Per-Entry Migration (L433–638)

- `_validate_fixture_entry(entry)` (L449–480): Pure validator for A entries. Checks `fixture_root` exists, is under `CORPUS_ROOT_REL`, parses finding, verifies `finding.path` starts with `<fixture_root>/source/`. Returns `(_FixtureValidation, None)` or `(None, reason)`.
- `migrate_fixture_entry(entry, dest, adjudicated_at)` (L483–514): Write path for A entries. Checks already-handled, validates, writes `case.json`/`finding.json`/`expected.json` (no `source/` copy). Returns `MigrationOutcome`.
- `_status_fixture_entry(entry, dest)` (L517–533): Report-only status for A entries. Returns `("present", None)`, `("pending", reason)`, or `("skipped", reason)`.
- `_validate_audit_entry(entry, commit)` (L543–566): Pure validator for B entries. Parses finding, checks file exists at commit via `git cat-file`, checks file count ≤ `MAX_FILES`. Returns `(_AuditValidation, None)` or `(None, reason)`.
- `migrate_audit_entry(entry, dest, commit, adjudicated_at)` (L569–625): Write path for B entries. Pre-fetches all file bytes before writing (atomicity guard — cleans up on failure with `shutil.rmtree`). Writes `source/`, `case.json`, `finding.json`, `expected.json`, and `facts/` sidecars. Returns `MigrationOutcome`.
- `_status_audit_entry(entry, dest, commit)` (L628–638): Report-only status for B entries.

### Cross-Check (L646–680)

- `_cross_check(manifest, split_path, origin)` (L646–680): Compares manifest entries of a given origin against the corresponding split file (`manifest-fixtures.json` / `manifest-audit.json`). Returns list of human-readable discrepancy lines (empty = exact match).

### Report Rendering (L694–899)

- `StatusRow` (L695): type alias `tuple[str, str, str, str | None]` — (slug, class, status, reason).
- `_status_rows(...)` (L698–710): Combines fixture and audit status dicts into sorted list of `StatusRow`.
- `_count_facts_sidecars(dest)` (L713–717): Deterministic re-scan glob count of `facts/*.facts.json` files under `dest`.
- `_render_report(...)` (L720–847): Full Markdown for `MIGRATION-REPORT.md`. Contains summary table, per-entry status, skipped entries, cross-check results, sidecar extraction notes.
- `_render_skipped_md(...)` (L850–869): Markdown for `MIGRATION-SKIPPED.md`.
- `_render_run_summary(...)` (L872–898): Stdout-only transient summary of this invocation's write pass — never written to a file.

### CLI (L906–1011)

- `_parse_only(raw)` (L906–909): Parses comma-separated slug list from `--only` arg.
- `build_arg_parser()` (L912–932): Configures argparse with `--only`, `--dest`, `--commit`, `--manifest`.
- `main(argv)` (L935–1011): Entry point. Loads manifest, resolves commit, runs write pass then report pass, writes report files, returns 0.

---

## Dependencies

### Internal imports
- `triage_bootstrap.load_manifest` (L88): Loads and returns manifest JSON.
- `osoji.__version__` (L90): Version string embedded in `case.json`.
- `osoji.corpus_emit`: `CORPUS_CASE_SCHEMA`, `CORPUS_EXPECTED_SCHEMA`, `MAX_FILES`, `_git`, `_language_for`, `_posix_join`, `_producer_of`, `_to_posix`, `_walk_strings`, `_write_json` (L91–102).
- `osoji.findings.Finding` (L103): Domain finding model with `from_dict`/`to_dict`.
- `osoji.hasher.compute_file_hash` (L104): Used to hash snapshotted source files for `source_hash` in facts sidecars.
- `osoji.plugins.base`: `FactsExtractionError`, `PluginUnavailableError` (L105).
- `osoji.plugins.python_plugin.PythonPlugin` (L106): Tree-sitter facts extractor.

### External
- `subprocess` for `git cat-file -e` and `git show` calls.
- `shutil.rmtree` for atomic cleanup on failed audit-entry migration.
- `dataclasses.replace` for non-mutating `Finding` field overrides.

---

## Critical Invariants

1. **Determinism**: No wall-clock timestamps. All date fields derive from `manifest["audited"]`. Reports are byte-identical across reruns over an unchanged tree.
2. **Accepted-case guard**: `_case_already_handled` checks both `dest/<category>/case_<slug>` and `CORPUS_ROOT/<category>/case_*_<slug>` to prevent resurrecting already-accepted entries.
3. **Atomicity**: `migrate_audit_entry` pre-fetches all bytes before any write; on exception, `shutil.rmtree` removes the partial case dir.
4. **`accepted: false`**: All migrated cases set `accepted: false` — promotion to live corpus is a separate human-driven step.
5. **Line-ending normalization**: `_normalize_snapshot_bytes` is applied before hashing and writing, so `source_hash` and disk content agree regardless of `core.autocrlf`.
6. **`--only` isolation**: Write pass respects `--only`; report pass always covers the full manifest. Reports never reflect per-run write scope.
