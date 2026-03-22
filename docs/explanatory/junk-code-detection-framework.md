# The Junk Code Detection Framework: Two-Phase Analysis with LLM Verification

"Junk code" in Osoji's vocabulary means code that exists in the codebase but provides no value: dead symbols that nothing calls, function parameters that no caller passes, configuration fields that nothing reads, CI/CD pipeline steps that reference deleted files, dependencies that nothing imports, and source files with no reachable purpose. This document explains the framework architecture that detects these problems, the two-phase pattern that all analyzers follow, and how to extend it.

## What is "junk code"?

Junk code is broader than "unused imports." A simple linter can flag an import that nothing references in the same file. Osoji's junk detection operates at the cross-file and cross-system level:

- A public function defined in module A that no other module in the project calls
- A function parameter with a default value that every call site omits
- A configuration schema field that no runtime code reads or writes
- A CI/CD workflow job that references scripts or paths that no longer exist
- A package dependency listed in `pyproject.toml` that no source file imports
- A source file that nothing imports and that serves no reachable purpose (no entry point reaches it)

Detecting these problems requires whole-project analysis, not single-file linting. And distinguishing genuine dead code from framework-registered callbacks, dynamically referenced symbols, or convention-based auto-discovery requires semantic reasoning that static analysis alone cannot provide.

## The two-phase pattern

Every junk analyzer in Osoji follows the same architectural pattern:

```
Phase 1: Cheap candidate scanning          Phase 2: LLM verification
(Python, no LLM, high recall)             (LLM, high precision)

Source code + symbols + facts              Candidates + full context
        |                                          |
        v                                          v
  AST / grep / import graph               LLM evaluates each candidate
  scanning to find suspicious              with surrounding code, cross-file
  symbols                                  references, and project context
        |                                          |
        v                                          v
  Candidate list                           Confirmed findings with
  (intentionally over-inclusive)            confidence, reason, remediation
```

### Why two phases?

**LLM-only analysis would be too expensive.** A typical project has thousands of symbols. Sending each one to an LLM for evaluation would cost hundreds of dollars per audit run. Phase 1 reduces the candidate set to a manageable size -- typically 10-50 symbols -- using fast, free static analysis.

**Static-only analysis would produce too many false positives.** A function with zero cross-file references might be dead code, or it might be a CLI entry point, a test fixture, a framework callback registered by convention, or a dynamically loaded plugin. Static analysis cannot distinguish these cases. The LLM can, because it understands the semantic context: the function's docstring, its location in the project, the conventions of the framework being used.

Phase 1 is intentionally over-inclusive (high recall, lower precision). It casts a wide net to avoid missing real dead code. Phase 2 is the precision filter, confirming or rejecting each candidate with reasoning.

## The framework types

### `JunkFinding` dataclass (`junk.py`)

Every confirmed junk finding shares the same structure:

- `source_path` -- relative path to the file containing the junk
- `name` -- identifier of the junk item (function name, parameter name, dependency name)
- `kind` -- what type of thing it is: `function`, `class`, `config_field`, `parameter`, `dependency`, `cicd_job`, etc.
- `category` -- the classification: `dead_symbol`, `unactuated_config`, `dead_parameter`, `dead_dependency`, `dead_cicd`, `orphaned_file`
- `line_start`, `line_end` (nullable) -- source location (with validation that `line_end >= line_start` when `line_end` is present)
- `confidence` -- float between 0.0 and 1.0
- `confidence_source` -- how the confidence was determined: `"ast_proven"`, `"llm_inferred"`, or `"heuristic"`
- `reason` -- human-readable explanation of why this is junk
- `remediation` -- suggested action to take
- `original_purpose` -- what the item was originally for, providing context for the developer deciding whether to remove it
- `metadata` -- extensible dict for analyzer-specific extra data

The `__post_init__` validation ensures `line_end >= line_start`, preventing invalid ranges from propagating through the system.

### `JunkAnalysisResult` dataclass

The container returned by every analyzer:

- `findings` -- list of confirmed `JunkFinding` objects (candidates that were verified as junk)
- `total_candidates` -- how many items were examined in Phase 1 (useful for understanding the filtering ratio)
- `analyzer_name` -- which analyzer produced these results

### `JunkAnalyzer` ABC

The abstract base class that all analyzers implement:

```
JunkAnalyzer (ABC)
  |
  +-- name (property)         -> str       e.g., "dead_code"
  +-- description (property)  -> str       e.g., "Detect cross-file dead code"
  +-- cli_flag (property)     -> str       e.g., "dead-code"
  +-- analyze_async()         -> JunkAnalysisResult
  +-- analyze()               -> JunkAnalysisResult  (sync wrapper)
```

The `analyze()` method is a sync wrapper that creates an LLM provider via `create_runtime()` (the rate limiter return value is discarded), runs `analyze_async()`, and cleans up. This allows analyzers to be invoked both from the async audit pipeline and from standalone CLI commands.

Before running, `analyze()` checks for the presence of `.osoji/symbols/` -- if no symbols data exists, the analyzer skips with a message directing the user to run `osoji shadow .` first.

## Concrete analyzers

Osoji ships six junk analyzers, registered in the `JUNK_ANALYZERS` list in `audit.py`:

### `DeadCodeAnalyzer` (`deadcode.py`)

Detects cross-file dead code -- public symbols that nothing in the project references.

**Phase 1:** Loads all symbols from `.osoji/symbols/`, loads the facts database, and performs textual reference scanning across all source files. For each public symbol, it counts how many other files reference that symbol name. Symbols with zero external references become candidates. A within-file transitive liveness analysis (`_compute_transitive_liveness()`) propagates liveness from externally-referenced symbols to symbols they call internally, avoiding false positives on private helpers used by public functions.

**Phase 2:** Sends candidates to the LLM in batches with the defining file content, shadow doc context, and grep hit evidence. The LLM confirms or rejects each candidate, providing confidence and reasoning.

Symbols proven dead by AST analysis (zero references and no dynamic usage patterns) receive `confidence_source: "ast_proven"` with confidence 1.0 and skip LLM verification entirely.

### `DeadParameterAnalyzer` (`deadparam.py`)

Detects function parameters that no caller ever passes.

**Phase 1:** For each exported function with optional parameters, scans all call sites in the project. If a parameter has a default value and no call site passes it, it becomes a candidate.

**Phase 2:** Sends candidates to the LLM with the function definition and all call site contexts. The LLM verifies whether the parameter is truly dead or is used via keyword arguments, spread operators, or other patterns that grep-based scanning might miss. It also identifies "gated branches" -- code paths inside the function that are unreachable because the parameter is never passed with a non-default value.

### `DeadPlumbingAnalyzer` (`plumbing.py`)

Detects unactuated configuration obligations -- schema fields or config options that are defined but never read at runtime.

**Phase 1:** Scans for configuration schemas (Pydantic models, dataclass definitions, JSON schemas) and cross-references their fields against runtime usage in the codebase.

**Phase 2:** LLM verification confirms whether each unactuated field is genuinely unused or is accessed through dynamic patterns (serialization, `**kwargs` unpacking, reflection).

### `DeadDepsAnalyzer` (`junk_deps.py`)

Detects unused package dependencies listed in manifest files.

**Phase 1:** Parses dependency manifests (`pyproject.toml`, `package.json`, `requirements.txt`, etc.), resolves package names to import names using a cache of known mismatches (e.g., `pillow` -> `PIL`, `pyyaml` -> `yaml`), and scans source files for imports matching each dependency.

**Phase 2:** LLM verification distinguishes between truly unused dependencies and those used through indirect mechanisms (build tools, runtime plugins, type stubs, peer dependencies).

### `DeadCICDAnalyzer` (`junk_cicd.py`)

Detects stale CI/CD pipeline elements. Note: `DeadCICDAnalyzer` overrides the base `analyze()` method and skips the symbols directory check, since CI/CD analysis does not depend on symbol data.

**Phase 1:** Discovers CI/CD files (GitHub Actions workflows, Makefiles, GitLab CI, Dockerfiles) and extracts their elements (workflow jobs, makefile targets). Checks whether referenced paths and scripts exist in the repository.

**Phase 2:** LLM verification evaluates each element with missing references to determine if it is genuinely stale or if the references are dynamically generated, external, or use glob patterns.

### `OrphanedFilesAnalyzer` (`junk_orphan.py`)

Detects source files that have no reachable purpose -- nothing imports them, and no entry point leads to them.

**Phase 1:** Uses a 6-phase pipeline: (1) builds import edges deterministically from the facts database, (2) identifies entry points using a small LLM call, (3) performs a first BFS from entry points over import edges to find reachable files, (4) discovers semantic relationships (non-import connections like plugin registration, convention-based loading) using a small LLM call, (5) performs a second BFS incorporating the semantic edges to reach additional files, and (6) verifies remaining orphan candidates using a medium LLM call. Files not reached by either BFS pass and not cleared by verification become candidates.

**Phase 2:** LLM verification evaluates each candidate with its shadow doc and purpose summary, distinguishing genuinely orphaned files from those registered through framework conventions or dynamic loading.

## Confidence scoring

The confidence model communicates how certain the system is about each finding:

- **1.0 with `ast_proven`** -- the dead code analyzer can prove with AST analysis that a symbol has zero references anywhere in the project and no dynamic usage patterns. No LLM involvement needed.
- **0.0-1.0 with `llm_inferred`** -- the LLM assessed the evidence and assigned a confidence level. Higher values indicate stronger evidence (e.g., a function with zero grep hits in a project with no dynamic loading). Lower values indicate uncertainty (e.g., a function that might be called through reflection).
- **0.0-1.0 with `heuristic`** -- a rule-based confidence assignment without LLM involvement.

The `confidence_source` field allows downstream consumers (scorecard generation, audit reports) to weight findings differently. An AST-proven dead symbol is a near-certainty; an LLM-inferred finding with 0.6 confidence warrants human review.

## Shared utilities

The `junk.py` module provides utilities used by all analyzers:

- `validate_line_ranges()` -- a `tool_input_validators` callback that checks `line_end >= line_start` across findings arrays in tool call outputs. This semantic constraint cannot be expressed in JSON Schema and is enforced through the self-correction loop.
- `load_shadow_content()` -- loads the shadow doc for a source file, used by analyzers to provide context to the LLM during Phase 2 verification.

## Integration with the audit pipeline

The `JUNK_ANALYZERS` list in `audit.py` registers all analyzer classes:

```python
JUNK_ANALYZERS: list[type[JunkAnalyzer]] = [
    DeadCodeAnalyzer,
    DeadParameterAnalyzer,
    DeadPlumbingAnalyzer,
    DeadDepsAnalyzer,
    DeadCICDAnalyzer,
    OrphanedFilesAnalyzer,
]
```

The audit orchestrator iterates this list, instantiates each analyzer, checks its `cli_flag` against enabled flags, and runs it. The `--junk` CLI flag enables all analyzers; individual flags (`--dead-code`, `--dead-params`, `--dead-plumbing`, `--dead-deps`, `--dead-cicd`, `--orphaned-files`) enable specific ones. The scorecard reports which phases were and were not run, using the `JUNK_ANALYZERS` registry to detect missing phases.

## Extensibility: adding a new analyzer

To add a new junk analyzer:

1. Create a new module (e.g., `junk_widgets.py`) with a class that subclasses `JunkAnalyzer`
2. Implement the three abstract properties (`name`, `description`, `cli_flag`) and `analyze_async()`
3. Follow the two-phase pattern: Phase 1 finds candidates cheaply, Phase 2 verifies with the LLM
4. Define tool schemas in `tools.py` for the LLM verification output
5. Add the analyzer class to `JUNK_ANALYZERS` in `audit.py`
6. Add a CLI flag in `cli.py` for enabling the new analyzer

The framework handles provider creation, rate limiting, progress reporting, and result aggregation. The analyzer only needs to implement candidate scanning and LLM verification logic.

## Design trade-offs

**Why an ABC rather than a Protocol?** The `JunkAnalyzer` ABC includes a concrete `analyze()` method that handles provider creation and cleanup. A Protocol would only define the method signatures without providing shared implementation. Since all analyzers need the same sync wrapper logic, the ABC avoids duplication.

**The precision/recall trade-off in Phase 1.** Phase 1 is intentionally over-inclusive. A function referenced only in a comment would pass Phase 1's grep-based scanning, but Phase 2 would recognize it as a false positive. Tightening Phase 1 to exclude comment references would risk missing real dead code that happens to have a similarly named comment. The cost of over-inclusion is more LLM calls in Phase 2; the cost of under-inclusion is missed findings.

**Why include `original_purpose` and `remediation`?** Reporting that a function is dead is not enough for the developer to act. They need to understand what the function was for (to assess risk of removal) and what to do about it (delete it, or convert it to a documented extension point). These fields make findings actionable rather than just flags.

**Language agnosticism.** Per the project's pipeline engineering principles, the framework and all analyzers must work identically for any programming language. The `JunkFinding` structure uses generic `kind` values rather than Python-specific types. Phase 1 scanning uses textual reference matching rather than language-specific import resolution. Phase 2 relies on the LLM's language-agnostic understanding to interpret references correctly regardless of whether the code is Python, TypeScript, Go, or Rust.

For how tool schemas are defined for verification, see the [LLM tool schemas and validation](llm-tool-schemas-and-validation.md) document. For how the LLM provider handles the verification requests, see the [LLM provider abstraction](llm-provider-abstraction.md) document.
