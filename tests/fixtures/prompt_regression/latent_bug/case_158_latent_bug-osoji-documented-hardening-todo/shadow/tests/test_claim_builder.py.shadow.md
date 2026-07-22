# tests\test_claim_builder.py
@source-hash: 2a63f3aceb61453f
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:32Z

## Purpose
Test suite for `osoji.claim_builder`, covering symbol extraction (ReDoS safety, PascalCase/backtick/ALL_CAPS rules), the debris wrapper `build_debris_claims` (V1-3 contract), the generalized `build_claims` (V1-4), evidence fingerprinting determinism, and schema configuration invariants.

## Key Sections

### Symbol Extraction Tests (L38–79)
- **`test_pascalcase_extraction_is_redos_safe` (L38–46)**: Feeds a 10 001-char pathological input to `_extract_all_symbols_from_debris` and asserts completion in < 1 second. Validates the result is `[pathological]` (one PascalCase-ish word).
- **`test_pascalcase_extraction_preserves_behavior` (L49–58)**: Parametrized; verifies class names, backtick-quoted names, and ALL_CAPS fallback symbols are found in extracted symbol list.
- **`test_pascalcase_no_duplicates_preserved` (L61–65)**: Backtick + plain-text duplicate collapses to one occurrence.
- **`test_all_caps_is_not_pascalcase` (L68–70)**: `ABCDEF` must not match the PascalCase predicate.
- **`test_backticked_call_form_extracts_function_name` (L73–79)**: Ensures `` `name()` `` form strips parens and extracts the symbol (regression for work#58).

### Fixtures & Helpers
- **`config` fixture (L82–84)**: Creates a `Config` with `root_path=temp_dir`, `respect_gitignore=False`. Depends on the `temp_dir` fixture (not defined here; assumed session/project-level).
- **`FakeFacts` (L87–94)**: Minimal stand-in for FactsDB; implements `cross_file_references(symbol, source_path)` via a dict lookup.
- **`debris(**over)` (L97–108)**: Factory for raw debris dicts with defaults `category="dead_code"`, `source="src/x.py"`, description `` "`old_helper` is defined but never used" ``.
- **`make_finding(**over)` (L208–221)**: Factory for `Finding` objects with `detector="debris:dead_code"`, `gap_type="reachability"`, `symbol="old_helper"`, `path="src/x.py"`.
- **`populate(temp_dir)` (L224–231)**: Writes `src/x.py` (`def old_helper`) and `src/y.py` (`from x import old_helper; old_helper()`) to disk for evidence-gathering tests.
- **`_bundle()` (L306–310)**: Returns a two-item `Evidence` list (kinds: `cross_file_reference`, `surrounding_code`) for fingerprint tests.

### `build_debris_claims` Tests (L111–202)
- **`test_eligible_with_refs_becomes_claim_with_evidence` (L111–124)**: `dead_code` finding + cross-file refs → single Claim with `cross_file_reference` evidence; `original_indices=[0]`, `would_escalate=0`.
- **`test_ineligible_finding_is_not_a_claim` (L127–136)**: `stale_comment` without `cross_file_verification_needed` flag → no claims.
- **`test_stale_comment_with_flag_is_eligible` (L139–149)**: `stale_comment` with `cross_file_verification_needed=True` + refs → 1 claim.
- **`test_eligible_without_evidence_counts_as_would_escalate` (L152–159)**: Eligible finding with no satisfiable evidence → `would_escalate=1`, no claims.
- **`test_original_index_mapping_skips_non_candidates` (L162–174)**: Mixed raw list (ineligible first, eligible second) → `original_indices=[1]` (uses raw-list positional index).
- **`test_debris_wrapper_sets_fingerprint` (L177–182)**: Claims produced by wrapper have non-None `evidence_fingerprint`.
- **`test_debris_latent_bug_type_defs_alone_suffice` (L185–202)**: `latent_bug` category; `symbols_by_file` containing the class definition alone satisfies the evidence gate (`type_signature` evidence produced); `would_escalate=0`.

### `build_claims` Tests (L234–300)
- **`test_build_claims_sets_fingerprint_and_evidence` (L234–244)**: Populated dir + `make_finding()` → `insufficient_evidence=False`, has `cross_file_reference` and `surrounding_code`, non-None fingerprint.
- **`test_build_claims_empty_bundle_leaves_fingerprint_none` (L247–254)**: Empty root → `insufficient_evidence=True`, `evidence_fingerprint=None` (decision 0014: cache-ineligible).
- **`test_build_claims_uses_category_schema` (L257–269)**: `detector="debris:stale_comment"` uses description-gap schema requiring `surrounding_code`.
- **`test_build_claims_falls_back_to_gap_type_default` (L272–279)**: Unknown detector → falls back to `DEFAULT_SCHEMA_BY_GAP_TYPE["reachability"]`; evidence kinds are subset of that schema's `kinds`.
- **`test_require_any_unmet_sets_insufficient_evidence` (L282–291)**: Stop-words-only claim text yields no scan needles → `insufficient_evidence=True`.
- **`test_preexisting_evidence_is_preserved` (L294–300)**: Pre-seeded `Evidence(kind="scanner_metadata")` on the finding stays first in the evidence list.

### Evidence Fingerprint Tests (L306–344)
- **`test_fingerprint_same_bundle_same_hash` (L313–314)**: Deterministic across equal bundles.
- **`test_fingerprint_is_order_insensitive` (L317–320)**: Reversed bundle → same hash.
- **`test_fingerprint_changes_when_payload_changes` (L323–329)**: Payload mutation → different hash; uses `dataclasses.replace`.
- **`test_fingerprint_changes_with_schema_version` (L332–335)**: Non-default `schema_version="cb-TEST"` → different hash.
- **`test_fingerprint_changes_with_impl_hash` (L338–344)**: Monkeypatches `osoji.claim_builder.compute_impl_hash` to return `"deadbeefdeadbeef"` → different hash.

### Schema Configuration Tests (L350–372)
- **`test_schema_entry_json_round_trip` (L350–355)**: `SchemaEntry.to_dict()` / `SchemaEntry.from_dict()` round-trips cleanly.
- **`test_schema_version_is_pinned` (L358–364)**: Asserts `CLAIM_BUILDER_SCHEMA_VERSION == "cb-3"`. Comment documents version history: cb-2 (CrossFileReferenceBuilder honors scanner hints), cb-3 (doc-category schema keys unprefixed).
- **`test_every_schema_kind_has_registered_builder` (L367–371)**: Every `kind` in all schema entries (both `CLAIM_BUILDER_SCHEMA` and `DEFAULT_SCHEMA_BY_GAP_TYPE`) must exist in `BUILDERS`; `require_any` must be a subset of `kinds`.

## Key Dependencies
- `osoji.claim_builder`: `CLAIM_BUILDER_SCHEMA`, `CLAIM_BUILDER_SCHEMA_VERSION`, `DEFAULT_SCHEMA_BY_GAP_TYPE`, `SchemaEntry`, `_extract_all_symbols_from_debris`, `build_claims`, `build_debris_claims`, `compute_evidence_fingerprint`, `compute_impl_hash` (monkeypatched at L342)
- `osoji.config.Config`
- `osoji.evidence`: `BUILDERS`, `Evidence`
- `osoji.evidence_builders.BuildContext`
- `osoji.findings.Finding`

## Architectural Notes
- `build_debris_claims` is a thin V1-3 wrapper that filters eligible categories (`dead_code`, `latent_bug`, always; `stale_comment` only when `cross_file_verification_needed=True`), counts would-escalate misses, and delegates to `build_claims`.
- `build_claims` is schema-driven: dispatcher keyed first by `category_of(finding)`, then by `gap_type`, then a hardcoded default.
- Fingerprint is schema-version + impl-hash + canonical (order-insensitive) bundle hash. Empty bundles must NOT get a fingerprint (None = cache-ineligible).
- The `temp_dir` fixture is not defined in this file — it is expected to be a project-level `pytest` fixture providing a `pathlib.Path`.
