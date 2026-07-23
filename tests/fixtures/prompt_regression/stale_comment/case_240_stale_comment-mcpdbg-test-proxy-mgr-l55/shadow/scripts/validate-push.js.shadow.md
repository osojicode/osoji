# scripts\validate-push.js
@source-hash: 5fe2e87364581da2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:24Z

## Purpose
CLI validation script that simulates CI behavior by cloning the repository into a temp directory, installing dependencies, building, and optionally running tests. Helps catch pre-push issues like uncommitted files, build failures, and state-dependent tests.

## Key Symbols

### `colors` (L12–19)
ANSI escape code constants for terminal output coloring (`reset`, `red`, `green`, `yellow`, `blue`, `cyan`).

### `log(message, color)` (L21–23)
Simple colored console output wrapper. Defaults to `colors.reset` if no color provided.

### `exec(command, cwd)` (L25–35)
Runs a command via `execSync` with `stdio: 'pipe'`, captures and returns stdout as UTF-8 string. Throws a wrapped `Error` with cause on failure. Defaults `cwd` to `process.cwd()`.

### `execWithOutput(command, cwd)` (L37–46)
Same as `exec` but uses `stdio: 'inherit'` to stream output directly to the terminal. No return value. Used when `config.verbose` is true.

### `validatePush(options)` (L48–200) — **primary exported function**
Async function that performs the full validation pipeline:
1. **L67–85**: Reads branch, commit SHA, and uncommitted changes via `git`; warns on dirty working tree
2. **L88–90**: Creates a temp directory at `os.tmpdir()/mcp-debugger-validate-<timestamp>`
3. **L93–101**: Clones the current repo with `git clone --no-local` into the temp dir
4. **L104**: Changes `process.cwd()` to the temp dir
5. **L107–109**: Checks out the exact commit SHA
6. **L112–118**: Runs `pnpm install` in temp dir
7. **L121–127**: Runs `pnpm build` in temp dir
8. **L130–154**: Conditionally runs tests:
   - `config.runTests=false` → skips entirely
   - `config.runSmoke=true` → runs subset: `tests/unit/index.test.ts tests/core/unit/server/server.test.ts`
   - default → runs full `pnpm test`
9. **L184–198** (`finally`): Always restores `process.cwd()` to `originalCwd`; removes temp dir unless `keepTemp` is set

**Options object:**
- `runTests` (default `true`): whether to run any tests
- `runSmoke` (default `false`): run quick smoke subset instead of full suite
- `verbose` (default `false`): stream command output to terminal
- `keepTemp` (default `false`): preserve temp dir after validation

**Returns** `true` on success, `false` on failure.

### `main()` (L203–250) — CLI entry point
Parses `process.argv` for flags (`--no-tests`, `--smoke`, `--verbose`/`-v`, `--keep-temp`, `--help`/`-h`), shows help text if requested, calls `validatePush(options)`, exits with code 0 (success) or 1 (failure/error).

## Architecture & Patterns
- **Entry guard** (L253–255): Only runs `main()` when invoked directly (`require.main === module`); also exports `validatePush` for programmatic use.
- **`process.chdir` side effect**: The script changes the working directory mid-execution (L104) and restores it in `finally` (L186). This means any unhandled exception before the `finally` block in external callers could leave `cwd` altered — but the `finally` block mitigates this within the function.
- **Two execution modes**: `exec` (silent, captures output) vs `execWithOutput` (verbose, inherits stdio), toggled by `config.verbose`.
- **Temp directory naming**: Uses `Date.now()` for uniqueness — potential (very unlikely) collision if invoked twice within the same millisecond.

## Dependencies
- `child_process.execSync` — command execution
- `fs-extra` — `ensureDir`, `pathExists`, `remove` for temp directory management
- `path`, `os` — path construction and temp dir resolution