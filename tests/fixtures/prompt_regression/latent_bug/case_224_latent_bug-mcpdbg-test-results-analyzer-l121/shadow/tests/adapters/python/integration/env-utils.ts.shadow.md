# tests\adapters\python\integration\env-utils.ts
@source-hash: 809fce482a16bae1
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:36Z

## Purpose
Windows CI environment utility that ensures a Python installation with `debugpy` is present and prepended to `PATH` before spawning MCP server processes in integration tests. No-ops on non-Windows platforms.

---

## Key Symbols

### `hasDebugpy` (L8–19) — internal
Checks whether a given Python executable has `debugpy` installed by running `python -m debugpy --version` with a 5-second timeout. Returns `true` iff exit status is 0.

### `installDebugpy` (L21–40) — internal
Runs `pip install --user --upgrade debugpy` via the given Python executable (120-second timeout). Returns `{ installed: boolean, log: string }` where `log` concatenates stdout+stderr for diagnostics. Catches spawn errors and returns `installed: false`.

### `ensurePythonOnPath` (L47–181) — **exported**
The sole public export. Mutates the passed `env` record's `PATH`/`Path` keys (Windows-only; early return on non-win32).

**Algorithm:**
1. **Guard** (L48–50): exits immediately on non-Windows.
2. **Collect candidate roots** in priority order (L58–90):
   - Priority 1 (L61–69): `pythonLocation` / `PythonLocation` from `env` or `process.env` (set by GitHub Actions `setup-python`).
   - Priority 2 (L72–90): All `x64` sub-dirs of `C:\hostedtoolcache\windows\Python\<version>\x64`, sorted by version numerically (ascending/oldest first).
3. **Select first root with debugpy** (L92–115): iterates candidates, verifies `python.exe` exists, calls `hasDebugpy`. Breaks on first match.
4. **Fallback — install debugpy** (L118–152): If none found, attempts `pip install debugpy` for each candidate root. If pip install succeeds and `hasDebugpy` confirms, selects that root. If all installs fail, falls back to first root where `python.exe` exists (with a warning that tests may fail).
5. **Mutate PATH** (L154–180): Prepends `<selectedRoot>` and `<selectedRoot>\Scripts` to `segments` (deduped case-insensitively). Writes back to both `env.PATH` and `env.Path`.

---

## Dependencies
- `node:fs` — `existsSync`, `readdirSync` for filesystem probing
- `node:path` — `path.join` for constructing exe/dir paths
- `node:child_process` — `spawnSync` for running Python subprocesses

---

## Architectural Notes
- **Windows-only logic**: all Python discovery is skipped on non-Windows. The function is safe to call unconditionally in test setup.
- **Mutation pattern**: mutates the caller-supplied `env` object in place (no return value); callers must pass the env dict that will be forwarded to the child process.
- **Deduplication**: uses a lowercased `Set` (`normalized`) to avoid duplicate PATH entries across both `env.PATH` and `env.Path` (both Windows PATH variants).
- **Sorted oldest-first**: hostedtoolcache versions are sorted ascending so the oldest/most-stable Python is tried first as a fallback.
- **Timeout values**: `hasDebugpy` uses 5s; `installDebugpy` uses 120s (network pip install).
