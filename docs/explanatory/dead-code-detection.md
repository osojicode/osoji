# Dead Code Detection: Cross-File Analysis with AST Proofs and Unified Triage

## The dead code problem

Finding unused code within a single file is straightforward -- any linter can flag an import that is never referenced. Finding dead code *across* files is fundamentally harder. A public function in one module may be imported by dozens of others, used via dynamic dispatch, registered through a framework decorator, or invoked through reflection. Simple unused-import tools cannot reason about these cross-file relationships: they operate on a single file at a time and lack the global view needed to determine whether a symbol is truly unreachable.

Osoji's dead code detection addresses this by combining two complementary propose-time strategies: a deterministic AST fast path over the facts graph, and a regex-based grep path that extends coverage to files lacking complete AST data. Since V1-5a, verification is no longer detector-private: candidates become reachability `Finding`s, the Claim Builder (`src/osoji/claim_builder.py`) assembles self-sufficient claims with cross-file evidence, and the unified Triage stage (`src/osoji/triage.py`) decides each claim under the shared three-gap rubric.

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
| path     |  | (regex scan)|
+----------+  +-------------+
    |              |
    v              v
+-------------------------------+
|   Transitive liveness (BFS)   |
|   filters false positives     |
+-------------------------------+
    |
    v
+-------------------------------+
|  Claim Builder (evidence:     |
|  repo sweep, surrounding code)|
+-------------------------------+
    |                    |
  clean zero          any textual
  (AST path)          hit / grep
    |                    |
    v                    v
+-------------+  +---------------+
| mechanical  |  | Triage claim  |
| confirm 1.0 |  | mode (LLM)    |
+-------------+  +---------------+
    |                    |
    v                    v
+-------------------------------+
|  confirmed Findings ->        |
|  JunkAnalysisResult/scorecard |
+-------------------------------+
```

### AST fast path (high confidence, no LLM cost)

When a file has been processed by a language plugin (such as the Python or TypeScript plugin) and all files that import from it also have AST-extracted facts, the system can resolve dead code deterministically. This logic runs inside `detect_dead_code_async` in `deadcode.py`:

1. **Load AST facts.** The `FactsDB` is instantiated from `.osoji/facts/` sidecar files. Each file's `extraction_method` field indicates whether facts came from AST parsing (`"ast"`) or LLM extraction (`"llm"`).

2. **Check completeness.** First, the defining file itself is checked for `extraction_method == "ast"`. Then the helper `_all_importers_ast_extracted` verifies that every file that imports from it also has `extraction_method == "ast"`. If either the defining file or any importer lacks AST facts, the file falls through to the grep path.

3. **Query cross-file references.** For each exported symbol, `facts_db.cross_file_references(symbol_name, source_path)` searches all other files for imports, calls, member writes, and re-exports of that symbol name.

4. **Confirm mechanically -- with a demotion guard.** AST-zero-reference candidates go through the Claim Builder like everything else, but without an LLM call: if the built `cross_file_reference` evidence shows a clean zero (no graph references AND no textual matches over a non-empty repo sweep), the finding is confirmed mechanically with `confidence=1.0` and `confidence_source="ast_proven"`. If the sweep finds *any* textual hit -- the symbol's name inside a quoted string (a potential reflection/registry dispatch key), a doc mention -- the claim is **demoted** to the ordinary Triage batch instead. The AST graph cannot see string-keyed reachability; the text sweep can.

This path is fast (pure Python dictionary lookups), free when clean (no API calls), and precise (no regex ambiguity). Its limitation is coverage: it only works when the full import chain has AST-extracted facts, which requires language plugins for all involved files. See the [language plugin system](language-plugin-system.md) for how plugins produce these facts.

### Grep path (broader coverage, LLM-verified)

Files without complete AST coverage fall through to the grep path, implemented in the `scan_references` function. This path works for any programming language because it uses regex rather than language-specific AST parsing:

1. **Build a regex pattern.** All known symbol names from `.osoji/symbols/` files are combined into a single compiled regex: `\b(sym1|sym2|...)\b`, sorted longest-first to avoid prefix-match ambiguity.

2. **Scan all repository files.** Every non-ignored, non-documentation file is read and scanned line by line. For each symbol match, the file path and line number are recorded in a `file_refs` dictionary.

3. **Count external references.** For each symbol, references from files other than the defining file are counted. The `_merged_refs` function handles qualified names by merging references to both `ClassName.method` and the bare `method` name.

4. **Classify candidates.** Symbols with zero external references become `zero_ref` candidates. Symbols with references below a dynamic threshold (10th percentile of non-zero counts, capped at 10) become `low_ref` candidates. Low-ref candidates carry `GrepHit` objects whose hit files become the claim's `priority_paths`.

5. **Claim Builder + Triage.** Each candidate becomes a `Finding` (via `finding_from_dead_code_candidate` in `findings_adapter.py`) carrying `scan_needles` (the qualified and bare symbol names) and `priority_paths` as propose-time `scanner_metadata`. The Claim Builder's `CrossFileReferenceBuilder` re-derives cross-file evidence with word-boundary hygiene, honest scan-scope totals, and positional flags (e.g. `in_string_literal` for potential dynamic-dispatch keys); `SurroundingCodeBuilder` adds the flagged region. Triage decides each claim in claim mode under `TRIAGE_SYSTEM_PROMPT`, returning a verdict, confidence, and reasoning per claim.

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

Both `_helper` and `_format_data` have zero cross-file references, but they are alive because `public_api` -- which is referenced externally -- calls them. The transitive liveness algorithm in `_compute_transitive_liveness` prevents these false positives:

1. **Build a within-file reference graph.** For each symbol in the file, the algorithm scans the symbol's line range for references to other symbols in the same file. This produces a `uses` dict: `{symbol_name: {set of referenced symbols}}`.

2. **Seed alive set.** Symbols with external references (checked via the `has_external_refs` callback) form the initial alive set.

3. **BFS propagation.** Starting from alive symbols, the algorithm follows the `uses` graph. If `public_api` uses `_helper`, and `_helper` uses `_format_data`, both are marked alive through transitive propagation.

4. **Filter results.** Only symbols that have zero external references themselves but became alive through transitivity are returned. The caller uses this set to exclude them from dead code candidates.

This algorithm runs on both the AST fast path and the grep path. It prevents the most common category of false positives -- internal helper functions that exist to serve a public API.

## Batching strategy

Triage claim batching is shared across the Phase-4 analyzers via `decide_junk_claims` in `src/osoji/junk_triage.py`:

- Claims from the same file are kept adjacent, then packed greedily into chunks of at most 12 claims (the V1-4 measured maximum per call under the Claim Builder's bounded payload caps). Chunks may span files -- claims are self-sufficient by construction, so no shared file content is needed.
- Chunks run concurrently through `gather_with_buffer` from `async_utils.py`. A failing chunk is bisected once and retried; a still-failing half keeps its claims undecided (`verdict=None`), which the analyzer then drops -- matching the legacy dropped-batch behavior.
- Rate limiting is handled by the injected rate-limited provider; per-analyzer token accounting is unchanged.

## Integration with the junk code framework

`DeadCodeAnalyzer` is a concrete implementation of the `JunkAnalyzer` abstract base class defined in `src/osoji/junk.py`. The ABC requires three properties and one async method:

| Property     | Value                                          |
| ------------ | ---------------------------------------------- |
| `name`       | `"dead_code"`                                  |
| `description`| `"Detect cross-file dead code (unused symbols)"`|
| `cli_flag`   | `"dead-code"`                                  |

The `analyze_async` method delegates to `detect_dead_code_async`, which returns decided `Finding`s (every verdict) plus the set of mechanically-confirmed keys. Only `verdict == "confirmed"` findings are mapped to `JunkFinding` instances; dismissed, uncertain, and undecided claims are dropped (candidates are hypotheses -- an unverified hypothesis is not reportable). Each finding carries:

- `category="dead_symbol"` -- the finding category for scorecard aggregation
- `confidence_source` -- either `"ast_proven"` (confirmed without an LLM call) or `"llm_inferred"`
- `confidence` -- `1.0` for mechanical confirms, the Triage confidence otherwise
- `reason` (the Triage reasoning trace) and `remediation` (the Triage suggested fix)

These findings flow into a `JunkAnalysisResult`, which is consumed by the audit orchestrator in `src/osoji/audit.py` and rendered in the audit scorecard.

## Design trade-offs

**AST-proven vs LLM-verified: the cost/precision spectrum.** Mechanical confirms are free and deterministic but require language plugin coverage for all files in the import chain *and* a clean text sweep. Triage-decided results cover any language but cost API tokens and introduce non-determinism. The dual-path design gives users the best of both: proven results where possible, Triage-decided results everywhere else -- and the demotion guard means "proven" now includes the text sweep the AST graph cannot perform.

**Grep as a fallback: regex limitations.** The text sweep uses `\b` word-boundary matching, which cannot understand dynamic access patterns (`getattr(obj, name)`), computed imports (`importlib.import_module(f"plugins.{name}")`), or aliased references. The evidence layer compensates positionally (quoted-span hits are flagged `in_string_literal`), and the unified rubric instructs the LLM to treat an exact-name hit inside a quoted string as a potential dynamic-dispatch key and to recognize framework magic, decorator-based dispatch, and dunder methods.

**Transitive liveness: preventing false positives at the cost of hidden dead chains.** If `public_api` calls `_helper` which calls `_dead_function`, and `public_api` itself becomes dead, all three are flagged. But if `public_api` is alive, the entire chain stays alive even if `_dead_function` is only reachable through unused code paths within `_helper`. This is a deliberate trade-off: false negatives (missing some dead code) are preferable to false positives (incorrectly flagging live code).

**Bounded claims over full files.** The legacy verifier sent the entire defining file (up to 100 KB) per batch; the Claim Builder sends the flagged region, targeted evidence, and honest sweep totals -- bounded, predictable token cost per claim, at the price of less ambient context. The prompt-regression baselines and the V1-4 ablation gate are the measurement that this trade holds.
