# Shadow Documentation Architecture: How Osoji Generates Semantic Code Summaries

Shadow documentation is the foundational data layer that everything else in Osoji builds on. Audits consume shadow docs to identify code quality issues. The facts database draws from structured facts extracted during shadow generation. Junk analyzers rely on symbol data that shadow generation produces. This document explains how the shadow documentation pipeline works, why it makes the design choices it does, and how the pieces connect.

## What shadow documentation solves

AI coding agents need context about codebases. Reading full source files is token-expensive and noisy -- a 1,000-line file might contain 500 lines of implementation detail irrelevant to the agent's task. Shadow docs solve this by providing a compressed, semantically rich summary layer:

- **Per-file summaries** (`<file>.shadow.md`) capture purpose, key components with line references, dependencies, and design notes
- **Directory roll-ups** (`_directory.shadow.md` in subdirectories, `_root.shadow.md` at project root) aggregate their children into cohesive module-level summaries
- **Structured sidecars** (symbols JSON, facts JSON, findings JSON, topic signatures) provide machine-readable metadata alongside the prose summaries

An agent can read `_root.shadow.md` to understand the project, drill into a directory's `_directory.shadow.md` for module-level context, or read a specific file's shadow doc -- all at a fraction of the tokens that reading the source would cost.

## Pipeline architecture

The main orchestration lives in `generate_shadow_docs_async()` in `src/osoji/shadow.py`. The pipeline runs in several stages:

```
1. File discovery      discover_files() via walker.py
        |
        v
2. Plugin AST          _run_plugin_extraction() for Python/TypeScript
   extraction
        |
        v
3. Staleness check     is_stale() per file via hasher.py
        |
        v
4. Concurrent LLM      generate_shadows_parallel() with gather_with_buffer()
   generation +         (cached files skip LLM calls; sidecar writes for
   sidecar writes       findings.json, symbols.json, facts.json, signatures.json
                        happen as part of per-file processing)
        |
        v
5. Directory roll-ups  generate_directory_shadows() dependency-based parallelism
        |
        v
6. Orphan cleanup      remove shadow docs for deleted source files
```

### Stage 1: File discovery

`discover_files()` in `src/osoji/walker.py` finds all source files to process:

- Uses `git ls-files` when available (respecting `.gitignore`)
- Falls back to recursive glob when git is unavailable
- Filters by configured extensions, ignore patterns, and `.osojiignore`
- Skips the `.osoji/` directory (Osoji's own output)
- Skips documentation candidates (files under `docs/`)
- Sorts results by depth, deepest first, for bottom-up processing

`discover_directories()` then identifies all directories containing processed files, also sorted deepest first.

### Stage 2: Plugin-based AST extraction

Before any LLM calls, `_run_plugin_extraction()` runs language-specific AST extraction plugins. Each plugin (Python, TypeScript) parses source files and extracts ground-truth structural facts: imports, exports, function calls, member writes, and string literals with their usage context.

This extraction is fast (pure AST parsing, no LLM) and produces facts that are structurally precise but semantically shallow. The LLM will later provide semantic classification (e.g., classifying string literal "kind" as identifier vs. config) that the AST cannot determine.

### Stage 3: Staleness checking

`is_stale()` determines whether a file needs regeneration by checking two hashes embedded in the existing shadow doc header:

- `@source-hash` -- does the source file content match? If not, the code changed.
- `@impl-hash` -- does the generation implementation match? If not, the prompts or pipeline changed.

If both match, the file is current and skipped. The `force` flag in config overrides this check.

### Stage 4: Concurrent LLM generation and sidecar writes

`generate_shadows_parallel()` processes all non-cached files concurrently using `gather_with_buffer()`, which bounds the number of in-flight async tasks. For each file:

1. Read the source content using `read_file_safe()` (with binary detection)
2. Add line numbers via `add_line_numbers()`
3. Estimate input tokens; if the file exceeds 150,000 tokens, use chunked processing
4. Call the LLM with the `submit_shadow_doc` tool forced via `tool_choice`
5. Extract structured data from the tool call response
6. Merge AST-extracted facts with LLM-extracted facts
7. Write the shadow doc, findings, symbols, topic signature, and facts sidecars

Each processed file produces up to five output files under `.osoji/`:

- `.osoji/shadow/<path>.shadow.md` -- the prose shadow doc with header
- `.osoji/findings/<path>.findings.json` -- code quality findings
- `.osoji/symbols/<path>.symbols.json` -- symbol definitions with roles
- `.osoji/signatures/<path>.signature.json` -- topic signature for coverage analysis
- `.osoji/facts/<path>.facts.json` -- structured import/export/call/string facts

### Stage 5: Directory roll-ups

After all files are processed, `generate_directory_shadows()` uses dependency-based parallelism -- leaf directories are processed first, and parent directories are processed once all their children complete. For each directory, it:

1. Collects the shadow doc bodies of direct child files and subdirectories
2. Computes a `children_hash` (Merkle-style hash of child content hashes)
3. Checks staleness against the cached `@children-hash`
4. If stale, sends child summaries to the LLM with the `submit_directory_shadow_doc` tool
5. Writes the directory shadow doc

This bottom-up ordering ensures that when a directory is processed, all its children (including subdirectories) already have current shadow docs. The Merkle-style children hash means a change in any file propagates staleness up through all ancestor directories.

### Stage 6: Orphan cleanup

After generation completes, shadow docs whose corresponding source files no longer exist are removed. This prevents stale documentation from accumulating as files are deleted or renamed.

## The hybrid approach: LLM + AST

The most important design decision in the shadow pipeline is using both LLM analysis and AST-based extraction, merging their results.

**Why not LLM-only?** LLMs hallucinate structural facts. They might report an import that does not exist, miss a string literal, or invent a function parameter. For facts that can be mechanically verified -- imports, exports, function signatures -- AST extraction provides ground truth.

**Why not AST-only?** AST parsing cannot capture architectural intent, design patterns, code quality issues, or semantic classification. It cannot tell you that a string literal `"dead_code"` is a project-internal category identifier rather than a configuration value. It cannot identify that a comment contradicts the code it describes.

**How they complement each other.** The `_merge_string_literals()` function in `shadow.py` illustrates the merge strategy: AST provides ground-truth structural fields (`usage`, `comparison_source`), while the LLM provides semantic classification (`kind`). The merge uses AST entries as the base, enriches them with LLM `kind` classifications matched by value and line number, and preserves any LLM-only entries (strings the AST missed). For imports, exports, calls, and member_writes, the AST results replace LLM results entirely when a plugin is available.

## Content hashing and staleness

The caching system in `src/osoji/hasher.py` prevents unnecessary LLM calls by detecting whether a shadow doc is current.

### Hash functions

- `compute_hash(content)` -- SHA-256 of UTF-8 encoded content, truncated to 16 hex characters
- `compute_file_hash(path)` -- hashes file contents, using `read_file_safe()` to handle binary files
- `compute_children_hash(entries)` -- Merkle-style hash from sorted `(name, content_hash)` pairs, catching file additions, removals, and content changes in a single comparison

### The two-hash scheme

Each shadow doc header contains:

```
# src/osoji/shadow.py
@source-hash: a1b2c3d4e5f6g7h8
@impl-hash: 9i8j7k6l5m4n3o2p
@generated: 2025-03-15T10:30:00Z
```

- **`@source-hash`** is the hash of the source file content at generation time. If the source file changes, this hash will not match `compute_file_hash()`, and the shadow doc is stale.
- **`@impl-hash`** is a composite hash over all Python files in `src/osoji/` that could affect shadow output (excluding CLI, hooks, observatory, stats, and safety modules). If the generation prompts, tool schemas, or pipeline logic change, this hash changes, and all shadow docs become stale.

This two-hash scheme means shadow docs are regenerated when either the code changes or the analysis tool changes, but not when unrelated project files change.

### Binary detection

`read_file_safe()` uses a three-stage algorithm to distinguish text from binary files:

1. **Null bytes** in the first 8KB -- catches most binary formats (images, compiled files)
2. **UTF-8 validity** -- if the content is valid UTF-8, it is treated as text regardless of byte patterns. This prevents false positives on files with multi-byte characters (CJK text, emoji, box-drawing characters)
3. **Non-text byte ratio** -- for non-UTF-8 files only, if more than 10% of bytes are outside the printable ASCII + whitespace range, the file is classified as binary

## Large file chunking

Files exceeding 150,000 estimated tokens (about 600KB of source code) are processed in chunks:

1. `_split_into_chunks()` divides the numbered content into chunks of approximately 120,000 tokens each, with 5% overlap at boundaries to preserve context
2. Each chunk is processed independently through `generate_file_shadow_doc_async()`, producing a partial shadow doc
3. `_generate_chunk_rollup_async()` sends all chunk shadows to the LLM with instructions to merge, deduplicate overlapping content, and produce a unified shadow doc

The overlap ensures that symbols or findings spanning a chunk boundary are captured by at least one chunk. The rollup step eliminates duplicates from the overlap regions.

## Key data structures

### `Finding` dataclass

Represents a code quality issue discovered during shadow generation:

- `category` -- one of: `stale_comment`, `misleading_docstring`, `commented_out_code`, `expired_todo`, `dead_code`, `latent_bug`
- `line_start`, `line_end` -- source file line range
- `severity` -- `"error"` or `"warning"`
- `description`, `suggestion` -- human-readable context
- `cross_file_verification_needed` -- flag for findings that reference behavior in other files

### `ShadowResult` dataclass

The per-file result carrying:

- `path` -- source file path
- `body` -- shadow doc content (markdown body without header)
- `cached` -- whether the result came from cache
- `error` -- error message if generation failed
- `input_tokens`, `output_tokens` -- LLM token counts
- `findings` -- list of `Finding` objects
- `symbols` -- list of symbol dicts with name, kind, line range, visibility
- `file_role` -- architectural classification string

### `MarkStaleResult` dataclass

Result from `mark_stale_docs()`:

- `stale_files` -- list of `(relative_path, reason)` tuples where reason is `"missing"`, `"stale"`, or `"stale-impl"`
- `marked_count` -- number of shadow docs that had stale warnings injected

## Retry logic and error handling

The pipeline handles failures at multiple levels:

- **LLM validation retries.** The self-correction loop in `LiteLLMProvider` (see [LLM tool schemas and validation](llm-tool-schemas-and-validation.md)) retries up to 3 times when the tool call output fails schema validation.
- **Rate limit retries.** The `RateLimitedProvider` (see [rate limiting and token budgeting](rate-limiting-and-token-budgeting.md)) retries on HTTP 429 and server errors with exponential backoff.
- **File write retries.** `_write_with_retry()` retries on transient OS errors (EINVAL, EIO) that occur on certain filesystems (e.g., DrvFs on WSL), with delays of 0.5s, 1.0s, and 2.0s.
- **Per-file error containment.** If any file fails completely, `process_file_async()` catches the exception and returns a `ShadowResult` with an error message. The pipeline continues processing other files.
- **Parallel task error containment.** `generate_shadows_parallel()` uses `return_exceptions=True` in `gather_with_buffer()`, converting unhandled exceptions to `ShadowResult` errors rather than aborting the entire batch.

## Design trade-offs

**Sidecar files vs. database storage.** Shadow docs are stored as plain files in `.osoji/shadow/`, mirroring the source tree structure. This choice prioritizes git-friendliness (shadow docs can be committed and diffed), transparency (developers can read them directly), and simplicity (no database setup or migration). The downside is filesystem overhead with many small files, but in practice this is negligible.

**Per-file generation vs. whole-project generation.** Each file is processed independently rather than sending the entire project to the LLM at once. This enables incremental updates (only regenerate changed files), parallelism (multiple files processed concurrently), and context window management (each file fits within the model's context). The cost is that per-file analysis cannot see cross-file relationships directly -- but the `cross_file_verification_needed` flag and the later audit phases address this limitation.

**The cost/quality trade-off of caching.** Aggressive caching (via source and impl hashes) minimizes LLM costs but means shadow docs can become stale between explicit regeneration runs. The `osoji check` command addresses this by scanning for staleness and injecting warning lines without regenerating, providing a fast staleness report. The pre-commit hook runs this check automatically.

**Bottom-up processing order.** Files are sorted deepest-first, and directories are processed after all files. This ensures that when generating a directory roll-up, all child content is already available. The alternative (top-down or random order) would require either multiple passes or deferred roll-up generation.
