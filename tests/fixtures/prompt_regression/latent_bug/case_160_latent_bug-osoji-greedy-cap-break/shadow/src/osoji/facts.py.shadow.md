# src\osoji\facts.py
@source-hash: 5e25a8a0d8542d53
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:56Z

## Purpose
Structured facts database for the osoji shadow documentation system. Loads `.facts.json` files from `.osoji/facts/` and provides query methods for import graph analysis, export tracking, symbol cross-referencing, and string contract checking.

## Key Types

### `FileFacts` (L12-31) — dataclass
Represents parsed facts for a single file (source or doc). Fields:
- `source`: normalized (forward-slash) file path
- `source_hash`: content hash for change detection
- `imports`, `exports`, `calls`, `member_writes`, `string_literals`: lists of dicts from LLM extraction
- `extraction_method` (L28): `"ast"`, `"llm"`, or `None` (legacy = llm)
- `classification`, `topics` (L30-31): doc-specific fields; `None` for source files

For doc files: `imports` stores source file references with `source` key; `exports`/`calls`/`member_writes`/`string_literals` are empty.

### `FactsDB` (L39-364) — class
In-memory database initialized from all `.facts.json` files in `config.root_path / SHADOW_DIR / "facts"`.

**Internal state:**
- `_files: dict[str, FileFacts]` — keyed by forward-slash-normalized source path

**Constructor (L46-49):** calls `_load(config)` immediately.

**Loading (`_load`, L51-75):**
- Uses `rglob("*.facts.json")` to discover all fact files
- Skips files missing `source` field
- Normalizes backslashes to forward slashes
- Applies `_only_dicts()` filter on all list fields
- Silently skips `json.JSONDecodeError` or `KeyError`

## Key Methods

| Method | Line | Purpose |
|---|---|---|
| `get_file(path)` | L77 | Lookup facts by path (normalizes separators) |
| `all_files()` | L81 | List all tracked file paths |
| `resolve_import_source(importing_file, source_specifier)` | L85 | Resolve import string → project-relative path or None |
| `_find_file(candidate_base)` | L152 | Try exact, extension, and index-file matches |
| `doc_files()` | L174 | Return paths of all doc files (classification is not None) |
| `docs_referencing(source_path)` | L178 | Doc files whose imports reference a given source file |
| `importers_of(source_path)` | L196 | Source files that import from a given path |
| `imports_of(file_path)` | L212 | Project files this file imports from (deduped) |
| `exported_names(file_path)` | L225 | Set of exported symbol names |
| `unused_exports()` | L233 | `(file, name)` pairs for exports never imported anywhere (respects wildcard `*`) |
| `strings_by_usage(usage, kind)` | L256 | `file → set[str]` of string values filtered by usage/kind |
| `string_entries_by_usage(usage, kind)` | L268 | `file → list[dict]` full string literal entries filtered by usage/kind |
| `cross_file_references(symbol_name, source_file)` | L280 | Find all cross-file references to a symbol across imports, calls, member writes, re-exports |
| `build_import_graph()` | L359 | Build full `file → set[imported_files]` adjacency graph |

## Import Resolution Logic (`resolve_import_source`, L85-150)

Two branches:
1. **Relative imports** (starts with `.`): 
   - Single-segment (no `/`): Python-style dotted (`..foo.bar`) — counts leading dots, goes up N-1 dirs, joins remainder
   - Multi-segment or `./`: JS-style path — uses `Path.resolve()` relative to `config.root_path`
   - Falls through to `_find_file()`
2. **Absolute/package imports**: replaces `.` with `/`, tries:
   - Direct suffix match against known files (strips common extensions)
   - `src/<first_segment>/...` and `<first_segment>/...` prefixes

`_find_file()` (L152-172) tries: exact match → common extensions (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.rs`) → index files (`__init__.py`, `index.ts`, `index.js`, `index.tsx`, `mod.rs`).

## Cross-File Reference Search (`cross_file_references`, L280-357)

For a given `(symbol_name, source_file)`, checks every other file for:
- Named imports (`names` list or `name_map` dict values)
- Direct calls (`to` field exact match or `.symbol_name` suffix)
- Qualified method dispatch: if `symbol_name` has `.`, also matches bare method calls when the calling file imports from the defining file (L317-338)
- Member writes matching the symbol as field name
- Re-exports with matching name

Returns list of evidence dicts: `{"file", "kind", "context", [optional "resolves_to_source"]}`.

## Helper

`_only_dicts(items)` (L34-36): Internal filter, discards non-dict entries from LLM list output.

## Dependencies
- `Config`: provides `root_path` (project root `Path`)
- `SHADOW_DIR`: constant for `.osoji` shadow directory name
- Standard: `json`, `dataclasses`, `pathlib.Path`

## Architectural Notes
- All path keys are normalized to forward slashes at load time and at each public method entry
- Doc files are distinguished from source files by `classification is not None`
- `importers_of` skips doc files (L203-204), `docs_referencing` skips source files (L188-189)
- `unused_exports()` treats wildcard `*` imports as consuming all exports from a file
