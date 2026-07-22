# src\osoji\junk_orphan.py
@source-hash: a8c4f191254b5dcf
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:42Z

## Orphaned File Detection via Purpose Graph and LLM Verification

Implements a multi-phase pipeline to detect source files that are unreachable from any entry point in the project's import graph. Uses deterministic Python analysis for graph construction and small LLM model calls for entry point identification and semantic relationship discovery. Final verdict uses the unified Triage system.

---

### Architecture: 6-Phase Pipeline (`detect_orphaned_files_async`, L298–417)

1. **Phase 1** (`_build_import_edges`, L42–90): Builds a bidirectional adjacency graph from symbol cross-references. Scans each file for occurrences of all known symbol names using a single compiled regex, adding edges between files that share symbols.

2. **Phase 2** (`_identify_entry_points_async`, L108–160): Batches up to 100 file signatures per LLM call using the `small` model tier. Forces tool use via `identify_entry_points` tool. Falls back to `_identify_entry_points_heuristic` (L163–180) on failure, which uses `file_role` (`"entry"`, `"test"`) and well-known filenames.

3. **Phase 3** (`find_orphans`, L250–270): BFS from entry points through the adjacency graph. Returns sorted list of unreachable file paths.

4. **Phase 4** (`_identify_relationships_async`, L196–245): Batches up to 50 disconnected files per LLM call, providing up to 200 connected files as context. Uses `identify_relationships` tool to find semantic (non-import) connections.

5. **Phase 5**: Second BFS after adding semantic edges. Skipped if no relationships found.

6. **Phase 6**: Converts surviving orphan candidates to `Finding` objects via `finding_from_orphan_candidate`, builds claims via `build_junk_claims`, and decides via `decide_junk_claims` (unified Triage). Returns `(decided_findings, total_candidates)`.

---

### Key Classes

**`OrphanCandidate`** (L30–38): Dataclass holding `source_path`, `purpose`, `topics`, `file_role`, `public_surface`. Populated from `.osoji/signatures/` data. Intermediate representation before triage.

**`OrphanedFilesAnalyzer`** (L420–474): Implements `JunkAnalyzer` interface. Properties: `name="orphaned_files"`, `cli_flag="orphaned-files"`. `analyze()` (L435–451) is a sync wrapper that calls `asyncio.run()` around `analyze_async()`. `analyze_async()` (L453–474) filters triage results to `verdict == "confirmed"` only, building `JunkFinding` objects with `kind="file"`, `category="orphaned_file"`.

---

### Signature Loading (`_load_signatures`, L275–293)

Reads `{root}/.osoji/signatures/**/*.signature.json`, skipping `_directory.signature.json`. Returns list of dicts with at minimum a `"path"` key.

---

### LLM Model Usage

- Both `_identify_entry_points_async` and `_identify_relationships_async` use `config.model_for("small")`.
- Entry points call uses `tool_input_validators` with a completeness check (L133–139) that requires every submitted path to receive a verdict.
- Reservation keys: `"junk_orphan.identify_entry_points"` and `"junk_orphan.identify_relationships"`.

---

### Important Constraints / Invariants

- The adjacency graph only contains files that have symbols data (`all_symbols`). Files without shadow docs are invisible to the graph.
- If no entry points are found, orphan detection returns `[], 0` (L358–360).
- `find_orphans` only considers files already present as keys in `adjacency`; entry points not in the graph are silently ignored (L258).
- `all_sigs` uses `sig_by_path.get(fpath, {})` so files without signatures get empty purpose/topics.
- Semantic edges are added mutably to `adjacency` in-place (L378–380), affecting the second BFS.

---

### Dependencies

- `config.model_for("small")`: selects model tier for both LLM phases
- `SHADOW_DIR`: base directory constant for `.osoji/`
- `load_all_symbols`, `load_file_roles`: from `.symbols` module
- `finding_from_orphan_candidate`: converts `OrphanCandidate` → `Finding`
- `build_junk_claims` / `decide_junk_claims`: unified triage pipeline
- `create_runtime`: builds the `LLMProvider` in the sync `analyze()` path
