# src\osoji\triage_exec.py
@source-hash: de5f1a8cfd7a6c01
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:35Z

## Overview
Read-only, repository-confined executor for Triage exploration mode (V1-3). Provides three LLM-callable retrieval tools (`read_file`, `grep`, `list_dir`) with safety invariants: read-only operations, root path confinement, and bounded output to prevent context window overflow. All errors are returned as `"Error: ..."` strings rather than raised exceptions.

## Key Constants
- `_SKIP_DIRS` (L34): Set of directories excluded from grep/list operations — `.git`, `.osoji`, `.hg`, `.svn`, `node_modules`, `__pycache__`. Relevance filter only, not a security boundary.

## Class: `ExplorationExecutor` (L37–196)
Primary class; instantiated per repository root.

### Constructor `__init__` (L40–51)
- `config.root_path.resolve()` stored as `self.root` — absolute, symlink-resolved
- Configurable output caps: `max_file_bytes=16_000`, `max_grep_matches=100`, `max_list_entries=200`

### Dispatch: `run(tool_name, tool_input)` (L55–70)
Routes tool calls by string name. Recognizes `"read_file"`, `"grep"`, `"list_dir"`. Returns `"Error: unknown tool '{tool_name}'"` for unrecognized names. Extracts args via `.get()` with safe defaults.

### Path Safety
- `_resolve(rel_or_abs)` (L74–84): Resolves path against root; returns `None` if it escapes `self.root`. Handles both relative and absolute input paths. Confinement check at L82: `resolved == self.root or self.root in resolved.parents`.
- `_rel(path)` (L86–89): Converts absolute path to POSIX-style root-relative display string.

### Tools
- **`read_file(path, start, end)`** (L93–119): Reads UTF-8 file (with error replacement). Supports optional 1-based inclusive line range slicing (L111–115). Truncates at `max_file_bytes` with `"…[truncated]"` suffix.
- **`grep(pattern, glob)`** (L121–154): Compiles `pattern` as Python regex; searches all files matched by `glob` (default `**/*`). Returns `"path:lineno: text"` rows, each line stripped and capped at 200 chars. Truncates at `max_grep_matches`.
- **`list_dir(path)`** (L156–175): Lists directory entries sorted alphabetically; dirs suffixed with `/`, skip-dirs excluded, capped at `max_list_entries`.

### Helper: `_iter_files(glob)` (L179–196)
Yields `Path` objects for all files under root matching `glob` (default `**/*`). Skips non-file entries and paths containing any `_SKIP_DIRS` component. **No `_resolve` root-containment check** — the docstring at L183–188 notes this as a V1-4 hardening TODO: glob patterns are LLM-supplied and not yet validated for escape or ReDoS.

## Dependencies
- `Config` from `.config` — provides `root_path: Path`
- `re`, `pathlib.Path` from stdlib

## Architectural Notes
- Language-agnostic: no parsing, just text retrieval
- Caller-supplied `glob` in `_iter_files` bypasses root-confinement check — noted as a known gap for production hardening (V1-4)
- `_iter_files` is only used by `grep`; `list_dir` iterates directly via `resolved.iterdir()`
