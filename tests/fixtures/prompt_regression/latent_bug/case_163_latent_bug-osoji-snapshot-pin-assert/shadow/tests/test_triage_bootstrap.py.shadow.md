# tests\test_triage_bootstrap.py
@source-hash: af059e3103591510
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:37Z

## Purpose
Offline test suite for the V1-4 bootstrap harness (`scripts/triage_bootstrap.py`). Exercises manifest loading and claim-building logic using only committed fixture snapshots — no LLM calls, no network, no `.osoji` corpus.

## Key Elements

### Module-level Constants (L14-15)
- `REPO_ROOT` (L14): Resolved path to the repository root, derived from `__file__`
- `HARNESS_PATH` (L15): Absolute path to `scripts/triage_bootstrap.py`

### Fixtures

#### `harness` (L18-23, scope=`module`)
Dynamically loads `scripts/triage_bootstrap.py` as a Python module using `importlib.util`. Returns the module object, giving tests direct access to its functions and constants. Single load per test session.

#### `manifest` (L26-28, scope=`module`)
Calls `harness.load_manifest(harness.DEFAULT_MANIFEST)` to retrieve the parsed manifest dict. Depends on the `harness` fixture.

### Test Functions

#### `test_manifest_loads_and_validates` (L31-32)
Asserts the manifest has exactly **54 entries**. Hard-coded sentinel — will break if manifest changes.

#### `test_build_mode_fills_evidence_for_fixture_entries` (L35-45)
- Filters manifest entries where `origin == "fixture"`
- Calls `harness.build_claims_for_entries(entries)` → `(claims, meta)`
- Asserts `len(claims) == len(entries)` (one claim per entry, no skips)
- Asserts `meta[*]["insufficient"]` is empty for all entries — the "zero-LLM gate" ensuring fixture snapshots are fully buildable
- Asserts every claim's `finding.evidence` is truthy and `finding.evidence_fingerprint` is not None

#### `test_fixture_entry_paths_are_prefix_stripped` (L49-52)
- Takes first fixture entry only
- Asserts `claims[0].finding.path` does NOT start with `"tests/fixtures"` — verifies the harness strips the fixture path prefix when building claim paths

#### `test_build_meta_reports_filled_kinds` (L55-60)
- Takes first fixture entry only
- Asserts `meta[0]["slug"]` matches `entries[0]["slug"]`
- Asserts `meta[0]["kinds"]` is a non-empty list — verifies evidence kind tracking is functional

## Architecture & Dependencies
- Dynamically imports the production harness module at test time rather than importing it statically; enables testing a script-style module not structured as a package
- All tests are offline — CI-safe since `.osoji` corpus is gitignored; test data lives under `tests/fixtures/prompt_regression/<case>/`
- Depends on harness API: `load_manifest`, `DEFAULT_MANIFEST`, `build_claims_for_entries`
- Claim objects expose: `finding.evidence`, `finding.evidence_fingerprint`, `finding.path`, `finding.id`
- Meta dicts expose: `slug`, `insufficient`, `kinds`

## Critical Invariants
- Manifest entry count is pinned at 54 (L32) — must be updated if manifest changes
- Fixture entries must always be buildable with zero LLM calls; any regression here indicates a gap in builder logic
- Path prefix stripping must not expose `tests/fixtures` in produced claim paths