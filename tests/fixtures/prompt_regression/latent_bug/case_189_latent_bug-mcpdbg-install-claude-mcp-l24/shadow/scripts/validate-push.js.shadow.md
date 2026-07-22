# scripts\validate-push.js
@source-hash: 5fe2e87364581da2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:29Z

## Purpose
Pre-push validation script that simulates CI environment by cloning the repo into a temp directory and running install, build, and (optionally) tests. Catches issues like uncommitted files, broken builds, and locally-dependent tests before they reach CI.

## Key Symbols

### `colors` (L12-19)
ANSI escape code constants for terminal output coloring: `reset`, `red`, `green`, `yellow`, `blue`, `cyan`.

### `log(message, color)` (L21-23)
Utility logger wrapping `console.log` with ANSI color support. Defaults to `colors.reset`.

### `exec(command, cwd)` (L25-35)
Runs a shell command with `stdio: 'pipe'` (captures output). Returns stdout as UTF-8 string. Throws a descriptive `Error` with `cause` on failure.

### `execWithOutput(command, cwd)` (L37-46)
Runs a shell command with `stdio: 'inherit'` (streams output to terminal). Used when `config.verbose` is true. Throws on failure.

### `validatePush(options)` (L48-200) — **primary exported function**
Async orchestrator that:
1. Reads current git branch, commit SHA, and uncommitted changes (L67-85)
2. Creates a temp dir at `os.tmpdir()/mcp-debugger-validate-<timestamp>` (L88-90)
3. Clones current working directory with `git clone --no-local` into temp dir (L93-101)
4. `process.chdir(tempDir)` (L104) — changes CWD for subsequent commands
5. Checks out the exact HEAD commit (L108-109)
6. Runs `pnpm install` (L113-118)
7. Runs `pnpm build` (L122-127)
8. Conditionally runs tests (L130-154):
   - Smoke mode: runs specific test files `tests/unit/index.test.ts` and `tests/core/unit/server/server.test.ts`
   - Full mode: runs `pnpm test`
   - `--no-tests`: skips entirely
9. `finally` block (L184-198): restores `originalCwd` via `process.chdir`, removes temp dir unless `keepTemp` is set

**Options:**
- `runTests` (default `true`) — run test suite
- `runSmoke` (default `false`) — run subset of tests only
- `verbose` (default `false`) — stream command output
- `keepTemp` (default `false`) — preserve temp dir after run

Returns `true` on success, `false` on failure.

### `main()` (L203-250) — CLI entry point
Parses `process.argv` flags: `--no-tests`, `--smoke`, `--verbose`/`-v`, `--keep-temp`, `--help`/`-h`. Prints help text and exits 0 on `--help`. Calls `validatePush(options)`, exits with code 0 (success) or 1 (failure/error).

## Architecture Notes
- CWD is mutated globally via `process.chdir` (L104, L186). The `finally` block ensures restoration even on failure.
- Temp directory name uses `Date.now()` for uniqueness (L51).
- `exec` vs `execWithOutput` branching is controlled by `config.verbose` throughout the validation steps.
- Module is both directly executable (L253-255 guard) and importable (`module.exports = { validatePush }` at L257).
- Smoke test command hardcodes specific test file paths (L134), which may become stale if those files move.