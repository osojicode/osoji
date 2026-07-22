# src\osoji\plugins\_legacy_python_ast.py
@source-hash: 6ffb129c75cf9278
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:35Z

## Python Legacy AST Plugin

Implements a Python language plugin using stdlib `ast` for deterministic, dependency-free extraction of imports, exports, calls, member writes, and string literals from Python source files.

### Architecture

Two-phase extraction:
1. **Per-file AST pass** (`_FileExtractor`, L150–468): visits each file's AST to collect raw facts
2. **Cross-file call resolution pass** (`annotate_call_sites`, L537): resolves call targets across the project

### Key Symbols

#### Module-level Constants
- `_FRAMEWORK_DECORATOR_NAMES` (L17–38): `frozenset` of decorator names (e.g., `property`, `classmethod`, `pytest.fixture`, `app.route`) that mark symbols as framework-managed and thus excluded from dead-code analysis
- `_FRAMEWORK_DECORATOR_SUFFIXES` (L41–53): `tuple` of decorator name suffixes (e.g., `.route`, `.handler`) for suffix-based framework detection

#### Internal Helpers (L56–148)
- `_decorator_name(node)` (L56–67): recursively resolves `ast.Name`, `ast.Attribute`, `ast.Call` decorator nodes to dotted strings
- `_has_framework_decorator(decorators)` (L70–78): returns `True` if any decorator matches known framework names or suffixes
- `_decorator_names(decorators)` (L81–83): returns list of resolved decorator name strings
- `_resolve_callee(node)` (L86–95): resolves `ast.Name`/`ast.Attribute` call targets to dotted names
- `_get_all_members(node)` (L98–112): extracts `__all__` from module AST; returns `None` on augmented assignment (can't reliably resolve `__all__ += [...]`)
- `_extract_string_list(node)` (L115–125): extracts `list[str]` from `ast.List`/`ast.Tuple` of string constants; returns `None` on non-constants
- `_current_scope(scope_stack)` (L128–130): returns current scope name or `"<module>"`
- `_collect_docstring_lines(body)` (L133–140): returns line numbers of docstring nodes so they can be excluded from string literal collection
- `_annotate_parents(tree)` (L143–147): adds `_parent` attribute to every AST node for parent-aware string classification

#### `_FileExtractor` (L150–468)
`ast.NodeVisitor` subclass. Stateful; one instance per file.

**Constructor params:** `relative_path`, `is_init` (bool, affects re-export detection), `all_members` (from `__all__`)

**State:**
- `_scope_stack: list[str]` — tracks current dotted scope (class/function nesting)
- `_depth: int` — nesting depth for top-level detection (0 = module level)
- `_class_scope_depth: int` — tracks class body depth to detect methods (depth==1 inside class)
- `_docstring_lines: set[int]` — pre-populated before `visit()` call to filter docstrings

**Visitor methods:**
- `visit_Import` / `visit_ImportFrom` (L187–239): collects imports with `is_reexport` flag; in `__init__.py`, all public imports are treated as re-exports
- `_handle_funcdef` (L249–270): emits export for top-level functions and class methods (depth==0 or depth==1 with class scope); uses `exclude_from_dead_analysis` for framework-decorated functions
- `visit_ClassDef` (L272–292): emits class exports with `bases` field; tracks scope and class depth
- `visit_Assign` / `visit_AnnAssign` (L294–331): top-level assignments → exports (kind: `"constant"` if `isupper()`, else `"variable"`); attribute assignments → `member_writes`
- `visit_Call` (L335–343): records all calls with `from_symbol` (current scope) and `to` (callee)
- `visit_Constant` (L370–468): classifies string constants by parent AST node type into: `produced` (dict value, return, call arg, keyword arg, collection element, default param), `checked` (equality/membership comparison with `comparison_source`), `defined` (constant assignment); skips docstrings, f-string parts, dict keys, and strings ≤1 char

#### `PythonPlugin` (L471–549)
Implements `LanguagePlugin` protocol.

**Properties:**
- `name` → `"python"`
- `extensions` → `frozenset({".py", ".pyi"})`

**`check_available`** (L482–483): no-op; stdlib `ast` is always available

**`extract_project_facts(project_root, files)`** (L485–549):
1. Filters to `.py`/`.pyi` files
2. Builds `file_set` of normalized relative paths via `normalize_path`
3. First pass: for each file — reads UTF-8 source, parses AST, extracts `__all__`, annotates parent nodes, pre-collects all docstring lines (module + all function/class bodies), runs `_FileExtractor.visit()`
4. Second pass: calls `annotate_call_sites(per_file, file_set)` for cross-file resolution
5. Constructs `ExtractedFacts` per file and returns as `dict[str, ExtractedFacts]`

### Export Shape
Each export dict contains: `name`, `kind` (`"function"` | `"class"` | `"constant"` | `"variable"`), `line`, `decorators`, `exclude_from_dead_analysis`. Classes additionally include `bases`.

### Import Shape
Each import dict contains: `source`, `names`, `line`, `is_reexport`, optional `name_map` (alias mapping).

### Key Design Decisions
- `__all__` with `+=` (AugAssign) causes `all_members` to be `None` → falls back to public-name heuristic (no underscore prefix)
- Framework-decorated symbols get `exclude_from_dead_analysis: True` to prevent false dead-code positives
- String literals with length ≤1 are always filtered out (`_add_string`, L356)
- Dict keys are intentionally skipped (structural, not contract strings)
- Parent annotation (`_annotate_parents`) must run before `visit()` for string context classification to work correctly
- `_docstring_lines` is populated externally before `visit()` is called (L528–531), not inside the visitor itself