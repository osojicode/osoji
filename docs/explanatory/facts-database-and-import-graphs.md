# The Facts Database: Import Graphs, Symbols, and Cross-File Analysis

## The problem: cross-file analysis needs structured data

Shadow documentation provides prose summaries of each file's purpose, components, and dependencies. This is valuable for human readers and LLM agents, but it is not enough for automated cross-file analyses. Detecting dead code requires knowing exactly which symbols are imported by which files. Finding string contract violations requires knowing which string literals are produced and checked across files. Mapping documentation coverage requires knowing which docs reference which source files.

These analyses need structured, queryable data: who imports what, who exports what, what symbols exist where, and what string literals appear in which contexts. The `FactsDB` class in `src/osoji/facts.py` provides this data by loading machine-readable sidecar files generated during shadow documentation processing.

## Facts file format

Each source file processed by Osoji gets a corresponding `.facts.json` sidecar file stored in `.osoji/facts/`. The file path mirrors the source tree: a source file at `src/osoji/audit.py` produces facts at `.osoji/facts/src/osoji/audit.py.facts.json`.

A typical facts file for a source file contains:

```json
{
  "source": "src/osoji/audit.py",
  "source_hash": "a1b2c3...",
  "extraction_method": "ast",
  "imports": [
    {
      "source": ".config",
      "names": ["Config", "SHADOW_DIR"],
      "line": 13,
      "is_reexport": false
    }
  ],
  "exports": [
    {
      "name": "AuditResult",
      "kind": "class",
      "line": 73,
      "decorators": [],
      "exclude_from_dead_analysis": false
    }
  ],
  "calls": [
    {
      "from_symbol": "run_audit",
      "to": "build_scorecard",
      "line": 245
    }
  ],
  "member_writes": [
    {
      "container": "self",
      "member": "issues",
      "line": 77
    }
  ],
  "string_literals": [
    {
      "value": "dead_symbol",
      "line": 150,
      "usage": "produced",
      "context": "argument to JunkFinding",
      "kind": "identifier"
    }
  ]
}
```

**Documentation files** have a different shape. They include a `classification` field (e.g., `"tutorial"`, `"reference"`) and a `topics` list, and their `imports` field stores references to the source files they document rather than code imports. Their `exports`, `calls`, `member_writes`, and `string_literals` fields are empty. The `classification` field is the key discriminant: if it is present (not `None`), the file is a documentation file; if absent, it is a source file.

## The `FileFacts` dataclass

The `FileFacts` dataclass in `facts.py` represents the in-memory parsed facts for a single file:

| Field              | Type                        | Purpose                                    |
| ------------------ | --------------------------- | ------------------------------------------ |
| `source`           | `str`                       | Forward-slash-normalized relative path      |
| `source_hash`      | `str`                       | SHA-256 hash (truncated to 16 hex characters) of the source file at extraction time |
| `imports`          | `list[dict]`                | Import declarations                         |
| `exports`          | `list[dict]`                | Exported symbols (functions, classes, constants) |
| `calls`            | `list[dict]`                | Function/method call sites                  |
| `member_writes`    | `list[dict]`                | Attribute assignments (`obj.field = value`) |
| `string_literals`  | `list[dict]`                | Classified string literal occurrences       |
| `extraction_method`| `str \| None`               | `"ast"`, `"llm"`, or `None` (legacy = LLM) |
| `classification`   | `str \| None`               | Doc classification (None for source files)  |
| `topics`           | `list[str] \| None`         | Doc topic tags (None for source files)      |

The `extraction_method` field is important for downstream analyses. The dead code detection AST fast path only trusts files with `extraction_method == "ast"` -- these have deterministic, complete extraction from a language plugin. Files with `"llm"` extraction may have incomplete or inaccurate facts.

## The `FactsDB` class

`FactsDB` is an in-memory database that loads all `.facts.json` files on construction and provides query methods for cross-file analysis.

### Construction and loading

```python
facts_db = FactsDB(config)
```

On construction, `FactsDB` scans `{root}/.osoji/facts/` recursively for `*.facts.json` files. Each file is parsed and stored in `self._files: dict[str, FileFacts]` with forward-slash-normalized paths as keys. The `_only_dicts` helper filters each list field to keep only dict entries, defensively handling malformed LLM output that may include plain strings where dicts are expected.

### Core query methods

**Single-file lookup:**
- `get_file(path)` -- returns `FileFacts` for a specific path, or `None`
- `all_files()` -- returns all file paths with facts data
- `doc_files()` -- returns paths of documentation files (where `classification is not None`)

**Import graph queries:**
- `imports_of(file_path)` -- returns project files that a file imports from, with import sources resolved to actual project paths
- `importers_of(source_path)` -- returns files that import from a given path (the reverse direction)
- `build_import_graph()` -- constructs a `dict[str, set[str]]` adjacency list of the full import graph
- `resolve_import_source(importing_file, source_specifier)` -- resolves an import specifier (e.g., `.config`, `osoji.facts`) to a project-relative file path, or `None` for external packages

**Export analysis:**
- `exported_names(file_path)` -- returns the set of exported symbol names
- `unused_exports()` -- returns `(file, name)` pairs for exports never imported anywhere

**Cross-file reference queries:**
- `cross_file_references(symbol_name, source_file)` -- searches all files except the defining file for imports, calls, member writes, and re-exports of a symbol name. Returns evidence dicts with file path, reference kind, and context.

**String literal tracking:**
- `strings_by_usage(usage, kind=None)` -- returns `file -> set of values` filtered by usage (`"produced"`, `"checked"`, `"defined"`) and optionally kind (`"identifier"`)
- `string_entries_by_usage(usage, kind=None)` -- same but returns full entry dicts instead of just values

**Documentation queries:**
- `docs_referencing(source_path)` -- returns doc file paths whose imports reference a given source file

### Import resolution

The `resolve_import_source` method handles multiple import styles:

- **Relative imports** (Python `..foo.bar`, JS `./foo`): resolved relative to the importing file's directory, walking up directories for each dot level
- **Absolute imports** (Python `osoji.facts`, JS `@scope/package`): checked against known project files, trying both direct matches and `src/` prefixed paths
- **File matching**: candidates are tested with common extensions (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.rs`) and index files (`__init__.py`, `index.ts`, `index.js`, `index.tsx`, `mod.rs`)

Returns `None` for external packages (imports that resolve to no project file), which is the key signal for the string contract checker's `_is_external_package` method.

## Symbol utilities (`symbols.py`)

The companion module `src/osoji/symbols.py` provides utilities for loading symbol data from `.osoji/symbols/` sidecar files. These files are distinct from facts files -- they focus on the public API surface of each source file.

- **`load_all_symbols(config)`** -- reads all `*.symbols.json` files and returns a dict mapping relative source paths to symbol lists. Doc-candidate files are excluded. Each symbol dict has keys: `name`, `kind` (function, class, constant, variable), `line_start`, and optionally `line_end` and `visibility`.

- **`load_file_roles(config)`** -- reads the `file_role` field from symbol files, returning a dict mapping source paths to role strings (e.g., `"test"`, `"schema"`, `"config"`). Used by dead code detection to skip test file symbols and by dead plumbing detection to find schema files.

- **`load_files_by_role(config, role)`** -- convenience filter returning paths with a specific role. For example, `load_files_by_role(config, "schema")` returns all schema files for plumbing analysis.

## How FactsDB serves downstream analyses

```
                    +----------+
                    | FactsDB  |
                    +----------+
                   /    |    |   \
                  /     |    |    \
                 v      v    v     v
          Dead code  String  Coverage  Observatory
          detection  contracts analysis  bundle
```

**Dead code detection** (`deadcode.py`): Uses `cross_file_references` for the AST fast path -- symbols with zero cross-file references are proven dead. Uses `importers_of` to check whether all importers have AST-extracted facts (the completeness check for the fast path). Uses `get_file` to read `exclude_from_dead_analysis` flags on exports. See [dead code detection](dead-code-detection.md).

**String contract checking** (`obligations.py`): Uses `string_entries_by_usage("checked", kind="identifier")` to build per-file checked string sets. Uses `imports_of` for the `_files_are_linked` check in fragility detection -- determining whether producer and consumer are connected through the import graph. Uses `resolve_import_source` to distinguish external packages from internal imports. See [string contract obligations](string-contract-obligations.md).

**Documentation coverage analysis** (`doc_analysis.py`): Uses `get_file()` to look up doc-reference entries (populated by `osoji shadow .`) and extract the source files each doc covers from its `imports` field. Falls back to regex matching against shadow doc filenames when FactsDB lacks doc entries. Uses import relationships to assess whether docs accurately reflect their referenced sources.

**Documentation diff** (`diff.py`): Uses `docs_referencing` to find documentation files that reference changed source files, enabling targeted documentation impact analysis.

**Observatory bundle** (`observatory.py`): Uses `build_import_graph` via `_build_import_graph_edges` to emit the `import_graph` edge list in the export bundle. Uses `_build_facts_summary` to include per-file import/export/call data in file nodes.

**Shadow doc generation** (`shadow.py`): Uses existing facts for incremental updates -- when a file's hash has not changed, its facts are reused rather than re-extracted.

## Design trade-offs

**File-based storage vs database.** Facts are stored as individual JSON sidecar files rather than a database. This simplifies the architecture (no schema migrations, no query language), integrates naturally with git (facts files can be committed and diffed), and allows partial regeneration (only changed files need new facts). The trade-off is that `FactsDB` loads all files into memory on construction, which costs memory proportional to the number of source files.

**Forward-slash normalization.** All paths in `FactsDB` are normalized to forward slashes on load and on query. This ensures cross-platform consistency -- facts generated on Windows work when analyzed on Linux, and vice versa. The normalization happens in `_load` (`source.replace("\\", "/")`) and in every query method.

**Eager loading on construction.** `FactsDB.__init__` loads all facts files immediately rather than lazily. This makes the query API simple (no async, no cache misses) and ensures consistent state throughout an analysis run. The cost is upfront memory allocation, but since facts files are small (typically a few KB each), this is manageable for most codebases.

**The doc/source discriminant via `classification` field.** The same `FileFacts` dataclass represents both source files and documentation files, distinguished by whether `classification` is `None`. This is pragmatic but non-obvious -- callers must remember to check `classification` when iterating `all_files()` to avoid mixing doc and source file results. Methods like `importers_of` explicitly skip files with `classification is not None` to avoid treating doc references as code imports.

**Defensive loading with `_only_dicts`.** LLM-extracted facts may contain malformed entries -- plain strings or numbers where dicts are expected. The `_only_dicts` filter applied during loading ensures that downstream code can safely call `.get()` on every entry without type errors. This aligns with Osoji's principle that the facts DB is noisy and should be consumed defensively.
