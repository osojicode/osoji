# The Language Plugin System: Extensible AST Fact Extraction

## Why plugins?

Different programming languages have fundamentally different import systems, export conventions, and AST structures. Python uses `import` statements, `__all__` lists, and leading-underscore visibility conventions. TypeScript uses `import`/`export` keywords with path-based module resolution. Rust uses `mod`, `pub`, and `use`. A single monolithic analyzer cannot handle this diversity without becoming an unmaintainable tangle of language-specific special cases.

Osoji's plugin system solves this by extracting language-specific concerns into discrete plugin modules. Each plugin knows how to parse one language family's AST and produce a unified output format (`ExtractedFacts`). The core framework remains language-agnostic -- it consumes `ExtractedFacts` regardless of which plugin produced them. This design is central to Osoji's pipeline engineering principle that language agnosticism is non-negotiable.

## The plugin contract: `LanguagePlugin` ABC

The `LanguagePlugin` abstract base class in `src/osoji/plugins/base.py` defines the interface every plugin must implement:

```python
class LanguagePlugin(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this plugin (e.g. 'python')."""

    @property
    @abstractmethod
    def extensions(self) -> frozenset[str]:
        """File extensions this plugin handles (e.g. frozenset({'.py', '.pyi'}))."""

    def check_available(self, project_root: Path) -> None:
        """Raise PluginUnavailableError if external tooling is missing."""

    @abstractmethod
    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        """Extract facts for all applicable files in the project."""
```

The key design decisions in this interface:

- **`extensions` is a `frozenset[str]`.** Plugins declare which file extensions they handle. The registry dispatches by extension, so each extension maps to exactly one plugin.

- **`extract_project_facts` operates on the whole project, not individual files.** This allows plugins to perform cross-file analysis (like Python's import resolution) in a single pass rather than needing multiple iterations.

- **`check_available` has a default no-op implementation.** Plugins with no external dependencies (like the Python plugin, which uses stdlib `ast`) inherit this default. Plugins with external requirements (like the TypeScript plugin, which needs Node.js) override it to raise `PluginUnavailableError` with an installation hint.

- **Input is a pre-filtered file list.** The `files` parameter contains paths already filtered by Osoji's walker (respecting `.gitignore`, `.osojiignore`, etc.). The plugin further filters to its own extensions.

## `ExtractedFacts` dataclass

The `ExtractedFacts` dataclass in `base.py` defines the unified output format that all plugins produce:

| Field            | Type                              | Purpose                                   |
| ---------------- | --------------------------------- | ----------------------------------------- |
| `imports`        | `list[dict[str, Any]]`           | Import declarations with source, names, line |
| `exports`        | `list[dict[str, Any]]`           | Exported symbols with name, kind, line     |
| `calls`          | `list[dict[str, Any]]`           | Function/method call sites                 |
| `member_writes`  | `list[dict[str, Any]]`           | Attribute assignments (`obj.field = value`) |
| `string_literals`| `list[dict[str, Any]] \| None`   | Classified string literal occurrences      |

The `string_literals` field uses a `None` vs empty list distinction that carries important semantic meaning:

- **`None`** means the plugin does *not* extract string literals. The LLM will handle string extraction independently during shadow generation. This is the default.
- **An empty list `[]`** means the plugin *does* extract strings and found none in this file. The LLM knows not to duplicate the work.

This distinction controls whether the LLM performs redundant string extraction. A plugin that returns `None` for `string_literals` tells the system "I didn't do this work; the LLM should." A plugin that returns `[]` says "I did the work and found nothing."

The `to_file_facts_dict(source, source_hash)` method serializes `ExtractedFacts` into the JSON format consumed by `FactsDB`, adding `source`, `source_hash`, and `extraction_method: "ast"` fields. The `extraction_method` tag is critical for the dead code detection AST fast path, which only trusts AST-extracted data.

## `PluginUnavailableError`

When a plugin's external dependencies are missing, it raises `PluginUnavailableError` with a human-readable message and an `install_hint` string:

```python
class PluginUnavailableError(Exception):
    def __init__(self, message: str, install_hint: str):
        super().__init__(message)
        self.install_hint = install_hint
```

This enables graceful degradation. When the TypeScript plugin cannot find Node.js or `ts-morph`, it raises `PluginUnavailableError("ts-morph not found", "Run: npm install --save-dev ts-morph")`. The caller can catch this, log the hint, and fall back to LLM-only extraction for those files. The system continues working -- just without the AST fast path for that language.

## The registry (`plugins/registry.py`)

The registry module provides extension-based plugin dispatch through a simple dictionary mapping:

```python
_REGISTRY: dict[str, LanguagePlugin] = {}  # extension -> plugin
```

Key functions:

- **`register_plugin(plugin)`** -- registers a plugin for all its declared extensions. If two plugins claim the same extension, the later registration wins.
- **`plugin_for(path)`** -- looks up the plugin for a file path by its suffix. Returns `None` if no plugin handles that extension.
- **`supported_extensions()`** -- returns a `frozenset` of all extensions with registered plugins.
- **`get_all_plugins()`** -- returns a deduplicated list of all registered plugins (since one plugin may be registered for multiple extensions).

## Auto-discovery via entry points

Plugin registration happens through two mechanisms, both triggered when the `osoji.plugins` package is imported.

### First-party plugins (eager registration)

The `__init__.py` of `osoji.plugins` calls `_register_first_party_plugins()`, which imports and registers the built-in plugins:

```python
def _register_first_party_plugins() -> None:
    from .python_plugin import PythonPlugin
    from .typescript_plugin import TypeScriptPlugin

    register_plugin(PythonPlugin())
    register_plugin(TypeScriptPlugin())
```

The imports are inside the function body (lazy imports) to avoid circular dependencies -- plugin modules import from `base.py`, and `__init__.py` re-exports from `base.py`. If the imports were at module level, the import cycle would cause `ImportError`.

### Third-party plugins (entry point discovery)

After first-party registration, `_discover_entry_point_plugins()` scans for plugins installed as Python packages with the `osoji.plugins` entry point group. Note: this function is defined in `registry.py` and imported/called in `__init__.py`:

```python
# In registry.py:
def _discover_entry_point_plugins() -> None:
    eps = importlib.metadata.entry_points(group="osoji.plugins")
    for ep in eps:
        plugin_cls = ep.load()
        plugin = plugin_cls()
        register_plugin(plugin)
```

A third-party plugin package would declare its entry point in `pyproject.toml`:

```toml
[project.entry-points."osoji.plugins"]
rust = "osoji_rust_plugin:RustPlugin"
```

On `pip install osoji-rust-plugin`, the `RustPlugin` class would be auto-discovered and registered on the next Osoji run.

### Module-level side effects

Both registration steps happen at module level -- importing `osoji.plugins` triggers `_register_first_party_plugins()` and `_discover_entry_point_plugins()`. This means plugins are available before any file processing begins, which is necessary because the walker needs to know supported extensions early in the pipeline.

## Built-in plugins

### Python plugin (`python_plugin.py`)

The Python plugin uses the stdlib `ast` module for parsing, making it always available with no external dependencies. It handles `.py` and `.pyi` files.

**Extraction process:**

1. **First pass: per-file AST extraction.** Each Python file is parsed with `ast.parse`. A `_FileExtractor` visitor walks the AST and extracts:
   - **Imports**: `import` and `from ... import` statements, with relative import handling, alias tracking via `name_map`, and re-export detection for `__init__.py` files.
   - **Exports**: Top-level function definitions, class definitions, and assignments. Respects `__all__` when present (via `_get_all_members`). Private names (leading underscore) are excluded unless listed in `__all__`.
   - **Calls**: Function/method call sites with resolved callee names and scope tracking.
   - **Member writes**: Attribute assignments (`obj.field = value`) with container resolution.
   - **String literals**: Context-classified using parent node analysis. Strings in equality comparisons are `"checked"`, dict values are `"produced"`, constant assignments are `"defined"`, return values and function arguments are `"produced"`.

2. **`__all__` handling.** If a module defines `__all__` as a simple list of string constants, only those names are considered exports. This prevents private implementation details from appearing as public API.

3. **Framework decorator detection.** Functions decorated with framework registration decorators (like `@app.route`, `@pytest.fixture`, `@click.command`) get `exclude_from_dead_analysis: True` on their export entries. The decorator lists `_FRAMEWORK_DECORATOR_NAMES` and `_FRAMEWORK_DECORATOR_SUFFIXES` cover common Python frameworks. This prevents dead code detection from flagging framework-registered handlers.

4. **Second pass: cross-file call resolution.** After all files are extracted, the plugin builds an import map (local name to defining file + original name) and counts call sites per (defining_file, symbol_name) pair. This cross-file resolution provides accurate call-site counts that single-file analysis cannot achieve.

5. **Parent annotation for string classification.** Before visiting, `_annotate_parents(tree)` adds `_parent` attributes to every AST node. The `visit_Constant` method uses these to classify strings based on their syntactic context (comparison, assignment, function argument, etc.).

### TypeScript plugin (`typescript_plugin.py` + `ts_runner/extract.js`)

The TypeScript plugin handles `.ts`, `.tsx`, and `.mts` files. Because TypeScript AST parsing requires a JavaScript runtime, it delegates to a Node.js subprocess running `extract.js`.

**Architecture:**

```
TypeScriptPlugin.extract_project_facts()
    |
    |  subprocess.run(["node", extract.js, ...tsconfigs])
    |  stdin: JSON {files: [...], workspacePackages: {...}}
    |
    v
extract.js (ts-morph)
    |
    |  stdout: JSON {path: {imports, exports, calls, member_writes}, ...}
    |
    v
Parse JSON -> dict[str, ExtractedFacts]
```

**Key details:**

- **`check_available`** verifies both `node` (via `shutil.which`) and `ts-morph` (via `node -e "require('ts-morph')"`) are installed. Missing either raises `PluginUnavailableError`.

- **Monorepo support.** `_find_all_tsconfigs` discovers `tsconfig.json` files scoped to directories containing actual source files (not gitignored data directories). `_detect_workspace_packages` reads `pnpm-workspace.yaml` or `package.json` workspaces to resolve internal package names to relative source directories.

- **Subprocess isolation.** Running TypeScript extraction in a separate Node.js process provides memory isolation (a large TypeScript project's AST does not bloat the Python process) and avoids embedding a JavaScript runtime in the Python package. The trade-off is startup latency and IPC overhead.

- **The plugin does not extract string literals** -- its `ExtractedFacts` have `string_literals` left at the default `None`, so the LLM handles string extraction for TypeScript files.

## LLM fallback

The plugin system operates in a hybrid model with LLM extraction. When a plugin extracts structural facts (imports, exports, calls, member writes), the LLM still handles:

- **Semantic analysis**: architecture understanding, design notes, and dependency descriptions in shadow docs
- **String literal classification**: when a plugin returns `string_literals=None`, the LLM extracts and classifies strings with semantic `kind` labels
- **Findings**: code quality issues, potential bugs, and documentation gaps

The `extraction_method: "ast"` tag on plugin-extracted facts distinguishes them from `"llm"` extraction. This distinction is consumed by:
- **Dead code detection**: the AST fast path requires `extraction_method == "ast"` for both the defining file and all importers (see [dead code detection](dead-code-detection.md))
- **FactsDB**: the `FileFacts.extraction_method` field stores the tag for downstream queries

When no plugin handles a file's extension, the LLM performs all fact extraction. The results are tagged with `extraction_method: "llm"` and are still usable by all downstream analyses, but with lower confidence for deterministic queries.

## Design trade-offs

**Why ABCs over Protocols?** The `LanguagePlugin` ABC provides a shared `check_available` default implementation and enforces method signatures at class definition time rather than at call time. Protocols would allow structural typing but would not catch missing method implementations until the plugin is actually called.

**Why extension-based dispatch?** Mapping file extensions to plugins is simple, fast (dictionary lookup), and unambiguous for the vast majority of files. The alternative -- content-based detection or shebang parsing -- adds complexity without significant benefit, since file extensions are a reliable language indicator in practice.

**Why eager registration?** Plugins must be available before any file processing begins because the walker and shadow generation need to know which extensions have plugins. Lazy registration would require either a pre-scan phase or deferred plugin resolution, adding complexity to the pipeline.

**The subprocess approach for TypeScript.** Running a Node.js subprocess for TypeScript extraction has startup cost (~1 second) and IPC overhead (JSON serialization). The benefit is complete isolation: the TypeScript compiler and `ts-morph` library run in their own memory space, the Python process stays lean, and plugin crashes do not take down the main process. The 120-second timeout (`subprocess.TimeoutExpired`) prevents runaway extraction from blocking the pipeline.

**Adding a new language plugin.** The pattern for a new plugin is:

1. Create a class extending `LanguagePlugin` in `plugins/`
2. Implement `name`, `extensions`, and `extract_project_facts`
3. Override `check_available` if external tooling is required
4. Register in `_register_first_party_plugins` (or via entry points for third-party plugins)

The plugin receives a list of pre-filtered file paths and returns `dict[str, ExtractedFacts]`. It does not need to interact with shadow docs, LLM providers, or the audit pipeline -- the framework handles all of that based on the `ExtractedFacts` output. See the [facts database documentation](facts-database-and-import-graphs.md) for how plugin output flows into `FactsDB`.
