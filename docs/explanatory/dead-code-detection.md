# Dead Code Detection: Cross-File Analysis with AST Proofs and LLM Verification

## The dead code problem

Finding unused code within a single file is straightforward -- any linter can flag an import that is never referenced. Finding dead code *across* files is fundamentally harder. A public function in one module may be imported by dozens of others, used via dynamic dispatch, registered through a framework decorator, or invoked through reflection. Simple unused-import tools cannot reason about these cross-file relationships: they operate on a single file at a time and lack the global view needed to determine whether a symbol is truly unreachable.

Osoji's dead code detection addresses this by combining two complementary strategies: a deterministic AST fast path that produces mathematically proven results, and a regex-based grep path that extends coverage to files lacking complete AST data. Both paths feed into the same output pipeline through the junk code analysis framework.

## Dual-path architecture

The detection system in `src/osoji/deadcode.py` uses two distinct strategies to identify unused public symbols. The choice of path depends on the availability of AST-extracted facts for both the defining file and all files that import it.

```
Source files
    |
    v
+-------------------------------+
|  Are AST facts available for  |
|  the file AND all importers?  |
+-------------------------------+
    |              |
   Yes             No
    |              |
    v              v
+----------+  +-------------+
| AST fast |  | Grep path   |
| path     |  | (regex scan |
|          |  |  + LLM)     |
+----------+  +-------------+
    |              |
    | confidence   | confidence
    | = 1.0        | = variable
    |              |
    v              v
+-------------------------------+
|   Transitive liveness (BFS)   |
|   filters false positives     |
+-------------------------------+
    |
    v
+-------------------------------+
|  JunkAnalysisResult           |
|  (findings -> scorecard)      |
+-------------------------------+
```

### AST fast path (high confidence, no LLM cost)

When a file has been processed by a language plugin (such as the Python or TypeScript plugin) and all files that import from it also have AST-extracted facts, the system can resolve dead code deterministically. This logic runs inside `detect_dead_code_async` in `deadcode.py`:

1. **Load AST facts.** The `FactsDB` is instantiated from `.osoji/facts/` sidecar files. Each file's `extraction_method` field indicates whether facts came from AST parsing (`"ast"`) or LLM extraction (`"llm"`).

2. **Check completeness.** First, the defining file itself is checked for `extraction_method == "ast"` (lines 586-588 of `deadcode.py`). Then the helper `_all_importers_ast_extracted` verifies that every file that imports from it also has `extraction_method == "ast"`. If either the defining file or any importer lacks AST facts, the file falls through to the grep path.

3. **Query cross-file references.** For each exported symbol, `facts_db.cross_file_references(symbol_name, source_path)` searches all other files for imports, calls, member writes, and re-exports of that symbol name.

4. **Produce proven results.** Symbols with zero cross-file references are flagged as dead with `confidence=1.0` and `confidence_source="ast_proven"`. No LLM call is needed -- the result is derived from complete, deterministic data.

This path is fast (pure Python dictionary lookups), free (no API calls), and precise (no regex ambiguity). Its limitation is coverage: it only works when the full import chain has AST-extracted facts, which requires language plugins for all involved files. See the [language plugin system](language-plugin-system.md) for how plugins produce these facts.

### Grep path (broader coverage, LLM-verified)

Files without complete AST coverage fall through to the grep path, implemented in the `scan_references` function. This path works for any programming language because it uses regex rather than language-specific AST parsing:

1. **Build a regex pattern.** All known symbol names from `.osoji/symbols/` files are combined into a single compiled regex: `\b(sym1|sym2|...)\b`, sorted longest-first to avoid prefix-match ambiguity.

2. **Scan all repository files.** Every non-ignored, non-documentation file is read and scanned line by line. For each symbol match, the file path and line number are recorded in a `file_refs` dictionary.

3. **Count external references.** For each symbol, references from files other than the defining file are counted. The `_merged_refs` function handles qualified names by merging references to both `ClassName.method` and the bare `method` name.

4. **Classify candidates.** Symbols with zero external references become `zero_ref` candidates. Symbols with references below a dynamic threshold (10th percentile of non-zero counts, capped at 10) become `low_ref` candidates. Low-ref candidates include `GrepHit` objects with surrounding context lines for LLM review.

5. **LLM verification.** Candidates are batched by defining file and sent to the LLM with the `verify_dead_code` tool. The LLM receives the defining file content (truncated to 100,000 characters for very large files), its shadow documentation, and grep hit contexts. It returns a verdict for each symbol with a confidence score and reasoning.

The grep path is necessary because AST facts are not always available -- for example, a Go or Rust file has no plugin yet, or a JavaScript file is in a project without `ts-morph` installed.

## Transitive liveness (BFS within-file propagation)

A zero-reference symbol is not necessarily dead. Consider this scenario:

```python
# api.py
def public_api():          # imported and called by other files
    result = _helper()
    return result

def _helper():             # zero external references
    return _format_data()

def _format_data():        # zero external references
    return {"status": "ok"}
```

Both `_helper` and `_format_data` have zero cross-file references, but they are alive because `public_api` -- which is referenced externally -- calls them. The transitive liveness algorithm in `_compute_transitive_liveness` (lines 84-134 of `deadcode.py`) prevents these false positives:

1. **Build a within-file reference graph.** For each symbol in the file, the algorithm scans the symbol's line range for references to other symbols in the same file. This produces a `uses` dict: `{symbol_name: {set of referenced symbols}}`.

2. **Seed alive set.** Symbols with external references (checked via the `has_external_refs` callback) form the initial alive set.

3. **BFS propagation.** Starting from alive symbols, the algorithm follows the `uses` graph. If `public_api` uses `_helper`, and `_helper` uses `_format_data`, both are marked alive through transitive propagation.

4. **Filter results.** Only symbols that have zero external references themselves but became alive through transitivity are returned. The caller uses this set to exclude them from dead code candidates.

This algorithm runs on both the AST fast path and the grep path. It prevents the most common category of false positives -- internal helper functions that exist to serve a public API.

## Batching strategy

LLM verification of grep-path candidates is organized into batches grouped by defining file. The batching logic enforces two limits:

- **`MAX_SYMBOLS_PER_BATCH = 10`**: No batch contains more than 10 symbols.
- **`MAX_EXTERNAL_FILES_PER_BATCH = 10`**: The total number of distinct external files referenced by grep hits in a batch is capped at 10.

Batching by file serves an important purpose: all candidates in a batch share the same defining file, so the LLM receives the file content once (truncated to 100,000 characters for very large files) and can reason about all symbols in context. This is more efficient than one call per symbol and produces better results because the LLM can see relationships between symbols (e.g., one wraps another).

Batches are processed in parallel using `gather_with_buffer` from `async_utils.py`, which bounds the number of concurrent in-flight tasks to avoid resource exhaustion. Rate limiting is handled separately by the RateLimitedProvider wrapper.

## Integration with the junk code framework

`DeadCodeAnalyzer` is a concrete implementation of the `JunkAnalyzer` abstract base class defined in `src/osoji/junk.py`. The ABC requires three properties and one async method:

| Property     | Value                                          |
| ------------ | ---------------------------------------------- |
| `name`       | `"dead_code"`                                  |
| `description`| `"Detect cross-file dead code (unused symbols)"`|
| `cli_flag`   | `"dead-code"`                                  |

The `analyze_async` method delegates to `detect_dead_code_async`, then converts the resulting `DeadCodeVerification` objects into `JunkFinding` instances. Each finding carries:

- `category="dead_symbol"` -- the finding category for scorecard aggregation
- `confidence_source` -- either `"ast_proven"` or `"llm_inferred"`, distinguishing the two paths
- `confidence` -- `1.0` for AST-proven results, variable for LLM-verified results
- `reason` and `remediation` -- human-readable explanation and suggested action

These findings flow into a `JunkAnalysisResult`, which is consumed by the audit orchestrator in `src/osoji/audit.py` and rendered in the audit scorecard.

## Design trade-offs

**AST-proven vs LLM-verified: the cost/precision spectrum.** AST-proven results are free and deterministic but require language plugin coverage for all files in the import chain. LLM-verified results cover any language but cost API tokens and introduce non-determinism. The dual-path design gives users the best of both: proven results where possible, LLM-verified results everywhere else.

**Grep as a fallback: regex limitations.** The grep path uses `\b` word-boundary matching, which cannot understand dynamic access patterns (`getattr(obj, name)`), computed imports (`importlib.import_module(f"plugins.{name}")`), or aliased references. The LLM verification step compensates: the system prompt instructs the LLM to recognize framework magic, decorator-based dispatch, dunder methods, and other liveness patterns that regex cannot detect.

**Transitive liveness: preventing false positives at the cost of hidden dead chains.** If `public_api` calls `_helper` which calls `_dead_function`, and `public_api` itself becomes dead, all three are flagged. But if `public_api` is alive, the entire chain stays alive even if `_dead_function` is only reachable through unused code paths within `_helper`. This is a deliberate trade-off: false negatives (missing some dead code) are preferable to false positives (incorrectly flagging live code).

**Batching granularity.** Per-file batches balance context quality (the LLM sees the whole file) against batch size (10-symbol cap prevents prompt overflow). Files with many candidates are split into multiple batches, each sharing the same file content but covering different symbol subsets.
