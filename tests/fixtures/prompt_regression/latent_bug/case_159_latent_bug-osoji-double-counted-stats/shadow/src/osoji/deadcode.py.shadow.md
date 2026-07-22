# src\osoji\deadcode.py
@source-hash: fb4961f17e0e0fad
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:54Z

## Cross-File Dead Code Detection

Implements dead code detection via two complementary paths:
1. **AST fast path** (L505–576): For files with fully AST-extracted import graphs, uses `FactsDB.cross_file_references` to find zero-ref symbols without grep. AST-proven clean zeros are confirmed mechanically at confidence 1.0; any textual hits demote to Triage.
2. **Grep reference scan** (L129–358): Regex-based multi-file sweep for non-AST files. Computes zero-ref and low-ref (≤10th-percentile threshold, capped at 10) candidates.

Both paths feed the unified Claim Builder + Triage pipeline (`build_junk_claims` / `decide_junk_claims`). The module does **not** own an LLM prompt or tool schema — LLM interaction is fully delegated to Triage.

---

## Key Data Structures

### `GrepHit` (L28–33)
Textual reference to a symbol found in another file. Fields: `file_path`, `line_number`, `context` (±5 lines).

### `DeadCodeCandidate` (L36–46)
A public symbol with zero or low external references. Fields: `source_path`, `name`, `kind`, `line_start`, `line_end`, `ref_count`, `grep_hits`.

---

## Core Functions

### `_merged_refs` (L49–59)
Merges qualified (`ClassName.method`) and bare (`method`) name references from `file_refs` dict. Used to avoid false "zero-ref" for class-qualified symbols.

### `_extract_context` (L62–71)
Returns ±5 lines of source around a line number (1-indexed input). Marks the matched line with `>>>`.

### `_compute_transitive_liveness` (L74–126)
BFS within-file liveness propagation. Builds an intra-file reference graph from symbol body text, seeds with externally-referenced symbols, propagates liveness. Returns zero-ref symbols that are transitively alive (used by a live symbol). Skips files with fewer than 2 symbols.

**Key invariant (L101–102):** Applies `line_end + 1` padding to compensate for LLM-extracted ranges that are 1 line short.

### `scan_references` (L129–358)
Main grep-based scanner. Steps:
1. Loads all symbols via `load_all_symbols`.
2. Builds a combined regex of all symbol names (longest-first to avoid prefix conflicts).
3. Scans all repo files (skipping `.osoji/`, ignore patterns, doc candidates).
4. Counts external file references per symbol.
5. Applies transitive liveness filter.
6. Computes 10th-percentile threshold (capped at 10) for low-ref classification.
7. Applies `exclude_from_dead_analysis` exclusions from `FactsDB`.
8. Returns `(zero_ref_candidates, low_ref_candidates)`.

### `_all_importers_ast_extracted` (L361–367)
Returns True iff every importer of `symbol_path` has `extraction_method == "ast"`. Gate for AST fast path eligibility.

### `_group_symbols_by_file` (L370–378)
Normalizes and groups a `{source_path: [sym_dict]}` mapping by normalized (forward-slash) path.

### `_build_interface_alive_methods` (L381–477)
Prevents false positives for interface/override/constructor methods. Four phases:
1. Collect class metadata (bases, decorators) from AST-extracted files.
2. Resolve base class names to defining files (same-file first, then imports).
3. Fixpoint propagation: if a base method has `exclude_from_dead_analysis` or is already alive, mark the derived class's same-named method alive.
4. Mark `__init__` alive for instantiated classes; mark `__post_init__` alive for dataclass classes with cross-file refs.

### `detect_dead_code_async` (L480–637)
Main orchestration coroutine. Flow:
1. Load `FactsDB`, symbols, file roles, interface alive set.
2. For each fully-AST-resolved file: collect zero-ref candidates, filter by interface/constructor liveness, apply transitive liveness.
3. Run `scan_references` for non-AST files.
4. Build `BuildContext` (L586).
5. For AST candidates: `build_junk_claims` → `_clean_zero_reference` check → mechanical confirm or demotion to Triage.
6. For grep candidates + demoted: `decide_junk_claims` (async LLM Triage).
7. Returns `(all_decided_findings, mechanical_keys)`.

### `_clean_zero_reference` (L640–655)
Checks if a claim's evidence shows an honest zero: the `cross_file_reference` evidence has no references, `files_scanned > 0`, and `truncated` is not set.

### `DeadCodeAnalyzer` (L658–703)
`JunkAnalyzer` subclass. Properties: `name="dead_code"`, `cli_flag="dead-code"`. `analyze_async` (L673) calls `detect_dead_code_async`, filters confirmed findings, builds `JunkFinding` objects with `confidence_source` set to `"ast_proven"` or `"llm_inferred"` based on `mechanical_keys`.

---

## Architectural Notes

- **Threshold logic (L283–291):** 10th percentile of non-zero ref counts, capped at 10. Files with zero non-zero counts use threshold=0 (only zero-ref candidates).
- **Path normalization:** All paths are normalized to forward slashes for cross-platform dict key consistency.
- **Symbol name merging:** Both qualified (`A.b`) and bare (`b`) forms are tracked simultaneously; `_merged_refs` unions them at lookup time.
- **Mechanical confirmation invariant:** Only AST-proven, clean-sweep zeros bypass LLM — any textual hit (dynamic dispatch risk) forces Triage.
- **`total_candidates` (L702):** Computes as `len(decided) + len(mechanical_keys)` — note this double-counts mechanical findings already included in `decided`; cross-file verification may be needed.
