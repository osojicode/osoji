# tests\test_findings.py
@source-hash: adedd1a33b7a6bd3
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:41Z

## Purpose
Test suite for the unified `Finding`/`Evidence` schema defined in `osoji.findings` and `osoji.evidence`. Validates ID computation, serialization round-trips, field defaults, gap type literals, and evidence kind enumeration.

## Structure Overview

### Helper
- `_make_finding(**overrides)` (L9-24): Factory that builds a `Finding` with canonical defaults (`detector="deadcode:dead_symbol"`, `gap_type="reachability"`, `path="src/osoji/foo.py"`, `line_start=10`, `line_end=20`, `symbol="old_func"`, etc.). Accepts keyword overrides for per-test variation.

### Test Classes

#### `TestFindingId` (L27-82)
Tests the determinism and sensitivity of the computed `Finding.id` (16-char hex string):
- **L28-32**: `id` is a 16-character valid hex string
- **L34-35**: Same inputs → same `id` (stability)
- **L37-47**: `id` changes when `detector`, `path`, `symbol`, or `contract_claim` changes
- **L49-53**: Line numbers do NOT affect `id` when `symbol` is present (anti-churn property)
- **L55-61**: When `symbol=None`, falls back to location (`line_start`/`line_end`) for distinctness
- **L63-65**: Explicitly supplied `id` is not recomputed
- **L67-70**: `symbol=None` + `line_start=None` + `line_end=None` yields a stable (non-crashing) id
- **L72-77**: JSON encoding of parts prevents delimiter collision (tests `compute_finding_id` directly)
- **L79-82**: `evidence_fingerprint` is excluded from id computation

#### `TestFindingSerialization` (L85-119)
Tests `Finding.to_dict()` / `Finding.from_dict()` round-trips:
- **L86-88**: Minimal finding survives round-trip with equality
- **L90-95**: `Evidence` objects inside a finding survive round-trip and are re-hydrated as `Evidence` instances
- **L97-99**: `id` is preserved across round-trip
- **L101-102**: `evidence_fingerprint` defaults to `None`
- **L104-106**: `evidence_fingerprint` survives round-trip
- **L108-111**: `to_dict()` output is `json.dumps`-safe with `default=str`
- **L113-119**: Triage fields (`verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity`) all default to `None`

#### `TestGapType` (L122-129)
- **L123-125**: `"uncategorized"` is an accepted `gap_type`
- **L127-129**: All four literal values (`"reachability"`, `"description"`, `"contract"`, `"uncategorized"`) are accepted

#### `TestEvidence` (L132-156)
- **L133-135**: `Evidence` round-trips through `to_dict()`/`from_dict()` with equality
- **L137-151**: `EVIDENCE_KINDS` is pinned to exactly 8 kinds: `ast_fact`, `cross_file_reference`, `shadow_doc_claim`, `scanner_metadata`, `git_blame`, `type_signature`, `surrounding_code`, `declared_intent`. Comment notes that growing this set requires a schema version bump.
- **L153-156**: `Evidence` with empty/default `payload` round-trips correctly (payload becomes `{}`)

## Key Dependencies
- `osoji.evidence`: `EVIDENCE_KINDS` (enum/set of valid evidence kind strings), `Evidence` (dataclass/schema with `kind`, `weight_hint`, `payload`, `to_dict`, `from_dict`)
- `osoji.findings`: `Finding` (dataclass/schema with `id`, `detector`, `gap_type`, `path`, `line_start`, `line_end`, `symbol`, `contract_source`, `contract_claim`, `observed_behavior`, `evidence`, `evidence_fingerprint`, `verdict`, `confidence`, `triage_reasoning`, `suggested_fix`, `severity`, `to_dict`, `from_dict`), `compute_finding_id` (standalone ID hashing function)

## Important Constraints Documented by Tests
1. `Finding.id` is a 16-hex-char hash; line numbers are excluded from the hash when `symbol` is set (anti-churn)
2. JSON encoding is used inside `compute_finding_id` to prevent delimiter injection attacks
3. `EVIDENCE_KINDS` is a versioned contract — changes require bumping `claim_builder.CLAIM_BUILDER_SCHEMA_VERSION`
4. `evidence_fingerprint` is not part of the finding id