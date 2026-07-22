# src\osoji\claim_builder.py
@source-hash: b876168098d97e4e
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:55Z

## Purpose

Assembles `Finding` objects into self-sufficient `Claim` objects by gathering evidence bundles according to a per-category schema, computing deterministic evidence fingerprints for cache keying, and providing the `build_debris_claims` V1-3 legacy entry point for Phase-3 audit.

---

## Key Constants

### `CLAIM_BUILDER_SCHEMA_VERSION` (L48)
String `"cb-3"`. Included in every `evidence_fingerprint` hash. Bumping this invalidates the V1-9 verdict cache globally.

### Schema Entry Singletons (L77–89)
- `_REACHABILITY_ENTRY`: kinds=(`cross_file_reference`, `surrounding_code`), require_any={`cross_file_reference`}
- `_CONTRACT_ENTRY`: alias for `_REACHABILITY_ENTRY`
- `_DESCRIPTION_ENTRY`: kinds=(`surrounding_code`, `declared_intent`, `shadow_doc_claim`, `cross_file_reference`), require_any={`surrounding_code`}
- `_LATENT_BUG_ENTRY`: kinds=(`surrounding_code`, `cross_file_reference`, `type_signature`), require_any={`cross_file_reference`, `type_signature`}

### `CLAIM_BUILDER_SCHEMA` (L93–120)
Main dispatch table: maps native category string (part after `:` in `Finding.detector`) → `SchemaEntry`. Covers reachability (`dead_code`, `dead_symbol`, `dead_parameter`, `unactuated_config`), contract (`obligation_implicit_contract`, `obligation_violation`), description (`stale_comment`, `misleading_docstring`, etc.), and `latent_bug`.

### `DEFAULT_SCHEMA_BY_GAP_TYPE` (L123–131)
Fallback when category not found in primary schema. Keys: `"reachability"`, `"contract"`, `"description"`, `"uncategorized"`.

### `DEBRIS_SCHEMA` (L136–142)
Variant schema for legacy debris findings with overridden `require_any` semantics (stale_comment uses `cross_file_reference` as gate instead of `surrounding_code`).

---

## Key Classes

### `SchemaEntry` (L51–74) — frozen dataclass
Configuration for evidence gathering per finding category.
- `kinds: tuple[EvidenceKind, ...]` — ordered evidence kinds to invoke
- `require_any: frozenset[EvidenceKind]` — sufficiency gate; claim is `insufficient_evidence` if non-empty and none of these kinds produced evidence
- `to_dict()` (L66): JSON-serializable representation
- `from_dict(data)` (L70): Deserialize from dict, used for JSON round-tripping

---

## Key Functions

### `category_of(finding)` (L145–149)
Extracts the native category from `finding.detector` by splitting on `:` and returning the part after it. Falls back to the full `detector` string if no `:` present.

### `compute_evidence_fingerprint(evidence, *, schema_version)` (L152–170)
Computes a stable hash over the evidence bundle + `compute_impl_hash()` + `schema_version`. Canonicalization: each Evidence serialized with `sort_keys=True`, bundle sorted lexicographically, then joined with newlines. Returns `None` for empty bundle (cache-ineligible, decision 0014).

### `build_claims(findings, ctx, *, schema)` (L173–216)
Core claim assembly loop:
1. Resolves `SchemaEntry` via `schema` → `DEFAULT_SCHEMA_BY_GAP_TYPE` → `"uncategorized"` fallback (L189–193)
2. Iterates `entry.kinds`, calling `BUILDERS.get(kind).build(finding, ctx)` (L196–203)
3. Determines `insufficient_evidence` from `require_any` gate (L204)
4. Merges existing `finding.evidence` with newly built evidence (L205)
5. Appends `finding.evidence_fingerprint` via `compute_evidence_fingerprint` (L211)
6. Returns list of `Claim` objects

### `_is_eligible(finding)` (L222–230) — internal
Legacy debris eligibility filter: passes `dead_code`, `latent_bug`, and `stale_comment` with `cross_file_verification_needed=True`.

### `build_debris_claims(config, raw_debris, *, facts_db, symbols_by_file)` (L233–268)
V1-3 legacy entry point for Phase-3 audit:
1. Builds `BuildContext` from config + optional facts_db/symbols_by_file (L250)
2. Filters by `_is_eligible` and requires `source` or `source_path` field (L257–260)
3. Converts each eligible dict to `Finding` via `finding_from_debris` (L262)
4. Calls `build_claims` with `DEBRIS_SCHEMA` (L263)
5. Tracks `would_escalate` counter for insufficient-evidence cases (L264–265)
6. Returns `(claims, original_indices, would_escalate)` — `original_indices[k]` maps `claims[k]` back to `raw_debris` index

---

## Re-exported Symbols (L34–39)
`BuildContext`, `_extract_all_symbols_from_debris`, `_infer_variable_type`, `_lookup_type_definitions` are imported from `.evidence_builders` and re-exported for legacy import compatibility (`# noqa: F401`).

---

## Architectural Notes
- Schema is data, not code: `SchemaEntry` is JSON-round-trippable, enabling future mutation surfaces (gepa v2).
- Fingerprint design: empty bundle → `None` prevents verdict cache collision across symbol-less findings sharing a `finding.id` (decision 0014).
- The `build_claims` resolution order (category → gap_type → uncategorized) ensures no finding is ever dropped due to schema gaps.
- `DEBRIS_SCHEMA` overrides `stale_comment.require_any` to preserve V1-3 legacy semantics where `cross_file_reference` (not `surrounding_code`) was the sufficiency gate.
- Comment at L99–102 clarifies that `obligation_*` prefixed keys in `CLAIM_BUILDER_SCHEMA` are reachable as of V1-5c because the adapter now emits prefixed categories — important for understanding schema dispatch correctness.