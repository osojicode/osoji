# src\osoji\obligations.py
@source-hash: 508c7fb1f2f50a72
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:53Z

## Overview
Cross-file string contract checker for the `osoji` code analysis tool. Detects two categories of issues: (1) **violations** — strings checked in one file but never produced/defined anywhere in the project; (2) **fragile implicit contracts** — strings produced in one file and checked in another with no shared constant definition linking them. Entry point is `run_all_contract_checks`.

---

## Data Models

### `ObligationViolation` (L17–26)
Legacy backward-compatible dataclass. Fields: `obligation_type`, `source_file`, `checking_file`, `description`, `evidence` (dict), `severity` (default `"warning"`), `confidence` (default `0.5`). Used only by `StringContractChecker.check()` for old callers.

### `StringOccurrence` (L30–34)
Lightweight struct for a single string literal occurrence: `file`, `line`, `context`, `comparison_source` (optional). Used internally during contract data collection and filtering.

### `StringContractData` (L38–42)
Aggregated map of string usages across the project:
- `producers`: value → list of `StringOccurrence` where usage=`"produced"`
- `checked`: value → list of `StringOccurrence` where usage=`"checked"`
- `defined`: value → list of `StringOccurrence` where usage=`"defined"`
- `all_produced_values`: union of `producers.keys()` and `defined.keys()`

### `ContractFinding` (L45–70)
Primary output dataclass. Fields:
- `finding_type`: `"violation"` or `"implicit_contract"`
- `contract_type`: e.g. `"string_contract"`
- `value`: single string value or `None` for grouped multi-value findings
- `producer_file`, `consumer_file`, `definer_file`
- `severity`, `confidence`, `description`, `evidence`, `remediation`
- Optional triage fields (filled externally by Phase 3.5): `contract_class`, `finding_id`, `verdict`, `triage_confidence`, `triage_reasoning`, `suggested_fix`

---

## Module-Level Constants

### Filter Sets
- `_RUNTIME_GLOBALS` (L140–155): Well-known runtime globals (Node.js, Python, HTTP, DOM) — comparison roots matching these are classified as external.
- `_COMMON_STRINGS` (L158–167): Very common strings (JSON Schema vocab, primitive type names, etc.) excluded from contract analysis.
- `_FILE_PATH_ROOTS` (L169–172): Comparison-source roots indicating filesystem path checks (e.g. `"filename"`, `"suffix"`).
- `_FILE_PATH_HINTS` (L174–177): Context keywords indicating file/path checks.
- `_SERIALIZED_KEY_ROOTS` (L179–181): Root identifiers suggesting serialized-data key access.
- `_SERIALIZED_KEY_HINTS` (L183–186): Context keywords for serialized/JSON key access.
- `_EXTERNAL_PROTOCOL_HINTS` (L188–191): Context keywords for wire protocol / API string literals.

### `CONTRACT_CHECKERS` (L865–867)
Registry list of `ContractChecker` subclasses. Currently contains only `StringContractChecker`. Used by `run_all_contract_checks`.

---

## Abstract Base Class

### `ContractChecker` (L215–234)
ABC with three abstract members:
- `contract_type` (property): string identifier for the checker type
- `description` (property): human-readable description
- `find_contracts()`: returns `list[ContractFinding]`

Constructor stores `facts_db` as `self.facts`.

---

## `StringContractChecker` (L241–721)

### Constructor (L253–257)
Eagerly calls `_collect_tool_names()` and `_collect_tool_schema_keys()` to populate noise-filter sets. Initializes `_data` cache as `None`.

### `find_contracts()` (L269–275)
Primary API. Collects contract data (cached), runs both violation and fragility checks, returns combined list.

### `check()` (L277–280)
Backward-compatible wrapper. Returns `list[ObligationViolation]` from violation findings only.

### `_collect_contract_data()` (L284–324)
Iterates all files via `facts_db.all_files()`, reads `string_literals` with `kind="identifier"`, partitions into `producers`/`checked`/`defined` maps. Cached in `self._data`.

### `_check_violations()` (L328–402)
Ratio-based algorithm:
1. Gets per-file checked entries via `facts_db.string_entries_by_usage("checked", kind="identifier")`
2. Filters test files and applies `_should_ignore_checked_occurrence` heuristics
3. Removes `_tool_names` from checked values
4. Computes `matched` (intersection with all produced values) and `unmatched`
5. Post-filters `unmatched`: removes tool schema keys, common strings, strings < 3 chars
6. **Skips** if `unmatched` is empty OR if `matched` is empty (all-external heuristic)
7. `confidence = match_ratio = len(matched) / len(checked_values)`
8. Emits one `ContractFinding(finding_type="violation")` per unmatched value

### `_check_fragility()` (L460–545)
Detects implicit contracts:
1. Finds `shared_values = producers.keys() ∩ checked.keys()`
2. Filters each value with `_is_plausible_identifier`
3. For each `(checker_file, value)`, finds fragile producers (those not linked to a shared definer via `_pair_robust`)
4. Selects best producer via `_files_are_linked`, definer membership, occurrence count, path tie-break
5. Emits one `ContractFinding(finding_type="implicit_contract")` per `(checker, value)` pair
6. Calls `_group_findings()` to collapse same-pair multi-value findings

### `_pair_robust()` (L547–564)
Returns `True` if both producer and checker are linked (directly or one hop) to a common definer file. Uses `_files_are_linked` for import-link checks.

### `_files_are_linked()` (L566–568)
Delegates to module-level `_imports_link`.

### `_is_plausible_identifier()` (L570–580)
Noise filter: rejects values shorter than 3 chars, in `_COMMON_STRINGS`, in tool names, or in tool schema keys.

### `_group_findings()` (L582–646)
Groups implicit contract findings by `(producer_file, consumer_file)`:
- Single-member groups pass through unchanged
- Multi-value groups produce one merged finding with `value=None`, `confidence = min(0.9, 0.5 + 0.1 * count)`, all values in evidence

### `_suggest_remediation()` (L648–664)
Generates suggestion based on shared path prefix. If common package prefix exists, names it; otherwise generic message.

### `_violations_as_legacy()` (L668–684)
Static method. Converts `ContractFinding` list (violations only) to `ObligationViolation` list for backward compatibility.

### `_is_external_origin()` (L688–712)
Checks if `comparison_source`'s root identifier is a runtime global (`_RUNTIME_GLOBALS`) or imported from an external (non-project) package via `_is_external_package`.

### `_is_external_package()` (L714–721)
Returns `True` if `facts_db.resolve_import_source()` returns `None` (not resolvable to a project file). Relative imports always return `False` (internal).

### Heuristic filters (ignore methods)
- `_should_ignore_checked_occurrence()` (L404–416): Gate combining all ignore heuristics
- `_should_ignore_produced_occurrence()` (L431–437): Checks file/path and external protocol hints only
- `_looks_like_file_or_path_occurrence()` (L439–443): Root in `_FILE_PATH_ROOTS` or context contains `_FILE_PATH_HINTS`
- `_looks_like_serialized_key_occurrence()` (L445–451): Root in `_SERIALIZED_KEY_ROOTS` AND context contains `_SERIALIZED_KEY_HINTS`
- `_looks_like_external_protocol_occurrence()` (L453–456): Context contains `_EXTERNAL_PROTOCOL_HINTS`
- `_looks_like_duck_typing_or_config_access()` (L418–429): `comparison_source` contains `"getattr("` or `".get("`

---

## Cross-Pair Clustering Functions (L747–858)

### `_imports_link()` (L747–755)
Returns `True` if `file_a` imports `file_b` directly, or if any intermediate import of `file_a` imports `file_b` (one-hop transitive). Used by `_pair_robust` and `_merge_cluster`.

### `_contract_identity()` (L758–762)
Returns a `frozenset[str]` key for clustering: `{value}` for single-value findings, `frozenset(evidence["values"])` for grouped findings.

### `_sharer_files()` (L765–773)
Collects all files (producer, consumer, definer, and all in evidence lists) that participate in a contract. Used for sharer-breadth ranking in `_merge_cluster`.

### `_merge_cluster()` (L776–828)
Collapses a group of same-contract pair-findings into one canonical finding:
- Anchor selected by: import-linkage of consumer→producer, confidence, sharer count, path tie-break
- Unions all producer/checker/definer file sets across the group
- Adds `evidence["contract_sites"]` (all `{producer, consumer}` pairs) and `evidence["site_count"]`
- Appends site list to description when multiple sites exist

### `_cluster_by_contract()` (L831–858)
Groups findings by `(finding_type, _contract_identity(f))`, merges multi-member clusters, sorts result by `(-confidence, consumer_file, producer_file)`.

---

## Entry Point

### `run_all_contract_checks()` (L870–882)
Instantiates all `CONTRACT_CHECKERS`, collects findings via `find_contracts()`, then calls `_cluster_by_contract()` to deduplicate to one canonical finding per distinct cross-file string contract.

---

## Private Helper Functions (module-level)

- `_is_test_file(path)` (L77–80): Returns `True` if path contains `tests/` or `test/` directory, or filename starts with `test_`.
- `_collect_tool_names()` (L83–101): Dynamically loads `.tools` module, calls all `get_*_tool_definitions()` functions, collects tool `.name` fields.
- `_collect_tool_schema_keys()` (L104–121): Loads `.tools` module, extracts property names and enum values from tool dicts with `"input_schema"`.
- `_extract_schema_keys(schema, keys)` (L124–137): Recursive JSON Schema property/enum extractor.
- `_comparison_root(expr)` (L194–198): Extracts root identifier from dotted/bracketed expression.
- `_occurrence_text(context, comparison_source)` (L201–203): Joins context and comparison_source lowercased for heuristic matching.
- `_contains_any(text, needles)` (L206–208): Substring membership test across a set.

---

## Key Architectural Patterns

1. **Two-phase detection**: Violations (checked but no producer) and fragile implicit contracts (both producer and checker exist cross-file without shared constant) are separate algorithms sharing a cached `StringContractData`.
2. **Ratio anchor heuristic** (L370–371): A file checking zero known-internal strings is assumed to be consuming external contracts entirely — skipped. Only files with partial matches produce violation findings.
3. **Signal conservation**: Clustering in `_cluster_by_contract` never drops findings — it collapses N per-pair findings for the same literal into 1 canonical finding with full evidence, so a single Triage verdict governs the whole cluster.
4. **Noise filters at multiple levels**: Tool names/schema keys, common strings, file-path heuristics, serialized-key heuristics, external protocol heuristics, duck-typing patterns — all applied before emitting findings.
5. **One finding per (checker, value) before grouping**: `_check_fragility` emits per-pair then groups within the same (producer, consumer) pair; cross-pair deduplication happens in `_cluster_by_contract`.
