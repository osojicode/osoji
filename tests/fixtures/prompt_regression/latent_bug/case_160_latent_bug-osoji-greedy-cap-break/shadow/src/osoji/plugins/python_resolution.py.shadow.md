# src\osoji\plugins\python_resolution.py
@source-hash: 2ce6f84fe47274c2
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:26Z

## Purpose
Shared, AST-free utility module for resolving Python cross-file imports and annotating call-site counts. Used verbatim by both the legacy `ast`-based plugin and the tree-sitter plugin to keep `call_sites` counts bit-identical across the migration.

## Key Functions

### `normalize_path` (L15-17)
Converts an absolute `Path` to a forward-slash project-relative string. Used as a preprocessing step before storing paths in `file_set`.

### `resolve_python_import` (L20-64)
Resolves a Python import source string (e.g., `"."`, `"..bar"`, `"mypackage.mod"`) to a project-relative forward-slash path string, or `None` for external/unresolvable packages.
- **Relative imports** (L30-55): Counts leading dots, walks up directories from the importer's location, then delegates to `find_python_file`.
- **Absolute imports** (L57-64): Converts dots to slashes, tries both `""` and `"src/"` prefixes via `find_python_file`.
- Input: `source` (raw import specifier), `importing_file` (project-relative path of the file doing the import), `file_set` (set of all known project-relative paths).

### `find_python_file` (L67-88)
Matches a module path candidate (no extension) to an actual file in `file_set`.
- Resolution order: exact match → `.py` → `.pyi` → `__init__.py` (L73-88).
- Returns the first match or `None`.

### `annotate_call_sites` (L91-153)
Mutates call records in `per_file` in-place to populate `call["call_sites"]` with cross-project call counts.

**Algorithm (two-pass):**
1. **Pass 1 – Build import maps** (L99-114): For each file, resolve all imports to their defining file and build a `local_name → (def_file, original_name)` lookup. Skips wildcard imports (`*`).
2. **Pass 2a – Count call sites** (L116-135): For every call in every file, resolve the callee's root through the import map. Increments `call_site_counts[(def_file, resolved_name)]`. Unresolved callees fall back to `(current_file, callee)`.
3. **Pass 2b – Annotate** (L137-153): Re-iterates calls (same resolution logic) and writes the count into `call["call_sites"]`.

**Input contract for `per_file`:** Each value must be an object (plugin record) exposing:
- `.imports` — iterable of dicts with keys `"source"`, `"names"` (list of local names), and optionally `"name_map"` (alias mapping local→original).
- `.calls` — list of dicts with key `"to"` (callee string); `"call_sites"` is added by this function.

## Architectural Notes
- **Zero AST dependency**: pure `Path`/`dict`/`str` logic, intentionally shareable across plugin implementations.
- **Migration contract**: Bit-identical results are required between the ast-based and tree-sitter plugins; this module is the single source of truth for that logic.
- **Duplicate resolution logic** (L140-152 mirrors L118-135): The callee-resolution block is deliberately repeated to avoid storing intermediate state between the counting and annotation passes.
- `defaultdict(int)` (L117) ensures missing keys return 0 without explicit initialization.
- Absolute import resolution tries `src/` prefix (L59) to support common Python project layouts.
