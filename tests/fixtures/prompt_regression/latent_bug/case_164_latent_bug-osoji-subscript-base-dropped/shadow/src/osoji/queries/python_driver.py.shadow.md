# src\osoji\queries\python_driver.py
@source-hash: 7e7dfa58a90b2777
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:56:27Z

## Purpose
Tree-sitter–based Python language plugin (V1-6a) for the osoji fact-extraction system. Transliterates the legacy `ast`-based `_FileExtractor` using tree-sitter CST queries, preserving bit-identical output with the original. Handles scope tracking, `__all__` gating, string classification, and cross-file call resolution.

## Key Design Decisions
- **Parity contract**: Output must be bit-identical to the `ast`-based legacy plugin. Deliberate quirks (scope stack, decorator walk order, chained assignments, membership tuples) are preserved intentionally — see module docstring L1-19.
- **Lazy runtime loading**: `tree_sitter` and `tree_sitter_python` are imported lazily (L75-85, L796-802) so `osoji` imports without the optional wheels.
- **Two-pass extraction**: First pass extracts per-file facts (L837-864); second pass performs cross-file call-site annotation via `annotate_call_sites` (L867).
- **Pre-scan for `__all__`**: A lightweight `_TSFileExtractor` prescan (L853-856) extracts `__all__` members before the full extraction run, so export gating is available from the start.

## Module-Level Constants (L35-72)
- **`_FRAMEWORK_DECORATOR_NAMES`** (L35-56): `frozenset` of decorator names (e.g., `"property"`, `"pytest.fixture"`, `"app.route"`) that set `exclude_from_dead_analysis: True` on exports.
- **`_FRAMEWORK_DECORATOR_SUFFIXES`** (L58-70): Tuple of decorator suffix patterns (e.g., `".route"`, `".handler"`) for suffix-based framework decorator detection.
- **`_INSTALL_HINT`** (L72): Pip install string for error messages.

## `_load_language()` (L75-85)
Lazily imports `tree_sitter` and `tree_sitter_python`; raises `PluginUnavailableError` on `ImportError`. Returns a `Language` object.

## `_TSFileExtractor` (L88-718) — Core per-file extractor
Mirrors the legacy `_FileExtractor`. Initialized with `src` (bytes), `is_init` (bool), `all_members` (pre-scanned `__all__` list or None), and `capture_ids` (dict of node-id sets keyed by capture name).

### State
- `imports`, `exports`, `calls`, `member_writes`, `string_literals`: output lists (L105-109)
- `_scope_stack`: tracks dotted scope for functions, bare name for classes (L111)
- `_depth`: nesting depth for export gating (L112)
- `_class_scope_depth`: tracks class nesting for method export (L113)
- `_docstring_lines`: line numbers of docstring nodes, to suppress string classification (L114)

### Key Methods
- **`extract(root)`** (L214-217): Entry point. Calls `collect_docstrings`, then walks top-level children.
- **`_walk(node)`** (L219-260): Dispatch by capture-id bucket. Special-cases `conditional_expression` to mirror `ast.IfExp` field order (L250-258).
- **`collect_docstrings(root)`** (L200-210): Pre-marks docstring line numbers across module, functions, and classes.
- **`_handle_import(node)`** (L271-292): Handles `import X` and `import X as Y`.
- **`_handle_import_from(node)`** (L331-335): Handles `from X import Y`. Delegates name parsing to `_import_from_names`.
- **`_handle_future_import(node)`** (L337-339): Handles `from __future__ import ...`, forces source to `"__future__"`.
- **`_handle_decorated(node)`** (L343-351): Routes decorated definitions to `_handle_funcdef` or `_handle_classdef` with collected decorator nodes.
- **`_handle_funcdef(node, decorator_nodes)`** (L358-394): Emits export record at depth 0 or method level (depth==1, class_scope>0). Walks params, body, decorators, return type in `ast` field order.
- **`_handle_classdef(node, decorator_nodes)`** (L396-437): Emits export at depth 0 only. Pushes bare class name (not dotted) onto scope stack. Walks superclasses, body, decorators.
- **`_handle_assignment(node)`** (L454-494): Emits exports for module-level identifier targets; records `member_writes` for attribute targets (plain `Assign` only, not `AnnAssign`). Walks sub-nodes in `ast` field order.
- **`_handle_call(node)`** (L498-513): Records call site with `from_symbol`/`to`/`line`. Walks function and arguments.
- **`_handle_string(node)`** (L578-588): Skips concatenation children (handled at concat level). Evaluates string value; walks f-string interpolations if unevaluable.
- **`_classify_string(node, value, line)`** (L590-715): Parent-context–based string classification. Cases: dict value → `"produced"`, comparison → `"checked"`, assignment → `"defined"`, return → `"produced"`, call argument → `"produced"`, keyword argument → `"produced"`, collection element → `"produced"`, multi-subscript → `"produced"`, type annotation contexts → various, default parameter → `"produced"`. Skips docstrings and standalone expression strings.
- **`_add_string(value, line, usage, context, comparison_source)`** (L517-537): Filters strings ≤1 char and docstring lines; appends to `string_literals`.
- **`_dotted(node, through_call)`** (L132-149): Resolves dotted names (identifiers and attribute chains); optionally passes through call nodes to get callee names.
- **`_is_exported(name)`** (L151-156): Checks against `all_set` if present; otherwise rejects underscore-prefixed names.
- **`_flatten_assignment(node)`** (L442-452): Static method. Unwraps chained assignments into `(targets_list, final_value)`, mirroring `ast`'s multi-target `Assign`.
- **`_string_value(node)`** (L547-561): Evaluates string literal via `ast.literal_eval`, wrapped in parens for multiline concat. Returns `None` for f-strings, bytes, or errors.

## Module-Level Helpers (L720-771)
- **`_iter_nodes(root)`** (L720-727): Depth-first document-order node iterator using an explicit stack.
- **`_get_all_members(extractor, root)`** (L730-754): Pre-scans module top-level for `__all__ = [...]` or `__all__ = (...)`. Returns `None` if augmented assignment (`+=`) is detected (can't reliably resolve).
- **`_extract_string_list(extractor, node)`** (L757-771): Extracts a flat `list[str]` from a list/tuple node. Returns `None` if any element is non-string.

## `PythonPlugin` (L774-878) — LanguagePlugin implementation
- **`name`** (L783-784): Returns `"python"`.
- **`extensions`** (L786-788): Returns `frozenset({".py", ".pyi"})`.
- **`check_available(project_root)`** (L790-791): Calls `_ensure_runtime()` to validate tree-sitter availability.
- **`_ensure_runtime()`** (L793-802): Lazy init of `Parser`, `Language`, and `.scm` queries. Idempotent.
- **`_capture_ids(root)`** (L804-820): Runs all loaded `.scm` queries via `QueryCursor`; buckets node IDs by capture name into a `dict[str, set[int]]`.
- **`extract_project_facts(project_root, files)`** (L822-878): Two-pass pipeline. Pass 1: per-file CST parse → `_TSFileExtractor.extract()`. Pass 2: `annotate_call_sites()` for cross-file resolution. Returns `dict[str, ExtractedFacts]`.

## Dependencies
- `..plugins.base`: `ExtractedFacts`, `LanguagePlugin`, `PluginUnavailableError`
- `..plugins.python_resolution`: `annotate_call_sites`, `normalize_path`
- `ast` (stdlib): only `literal_eval` for string value recovery (L23)
- `tree_sitter`: `Language`, `Parser`, `QueryCursor` (lazy imports)
- `tree_sitter_python`: `language()` (lazy import)
- `. load_queries`: loads `.scm` query files for `"python"` language (L802)
