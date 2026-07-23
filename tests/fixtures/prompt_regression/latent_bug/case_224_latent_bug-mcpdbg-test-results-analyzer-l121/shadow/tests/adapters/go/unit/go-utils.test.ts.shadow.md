# tests\adapters\go\unit\go-utils.test.ts
@source-hash: be00a2c0f0c38aa1
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:38Z

## Purpose
Unit test suite for Go adapter utility functions (`go-utils`) from the `@debugmcp/adapter-go` package. Tests executable discovery, version parsing, Delve DAP support checking, and platform-specific search path generation.

## Test Structure

### Top-level suite: `go-utils` (L25–353)
- **Setup (L28–35):** `beforeEach` clears all mocks and creates a `mockLogger` with `debug`, `info`, `error` vi.fn() stubs.
- **Teardown (L37–40):** `afterEach` clears mocks and unstubs all globals.

### `child_process` mock (L15–21)
`spawn` is replaced with a `vi.fn()` while preserving all other exports from the actual module. `mockSpawn` (L23) holds the typed mock reference used in test implementations.

---

### `findGoExecutable` tests (L42–79)
Tests run only on the **current platform** (cross-platform mocking of `process.platform` noted as unreliable — L43).
- **L47–54:** Returns preferred path when `fs.promises.access` resolves.
- **L56–69:** Finds `go` binary from `PATH` env by stubbing `fs.promises.access` to resolve only for the expected path.
- **L71–77:** Throws `'Go executable not found'` when access fails everywhere and `PATH` is empty.

### `findDelveExecutable` tests (L81–129)
Same platform restriction as `findGoExecutable`.
- **L86–93:** Returns preferred path when `fs.promises.access` resolves; verifies `mockLogger.debug` contains `'preferred'`.
- **L95–117:** Finds `dlv` in `$HOME/go/bin/` with HOME/USERPROFILE/GOPATH/GOBIN stubbed.
- **L119–128:** Throws `'Delve (dlv) not found'` when nothing is accessible.

### `getGoVersion` tests (L131–193)
Uses `mockSpawn` to simulate subprocess behavior via `EventEmitter` with `stdout`/`stderr` sub-emitters.
- **L132–148:** Parses `'go version go1.21.0 darwin/arm64\n'` → `'1.21.0'`
- **L150–166:** Parses `'go version go1.22 linux/amd64\n'` (minor-only) → `'1.22'`
- **L168–179:** Returns `null` on `'error'` event from spawn.
- **L181–192:** Returns `null` on non-zero exit code.

### `getDelveVersion` tests (L195–239)
- **L196–212:** Parses `'Version: 1.21.0'` line from multi-line output → `'1.21.0'`
- **L214–225:** Returns `null` on spawn error.
- **L227–238:** Returns `null` on non-zero exit.

### `checkDelveDapSupport` tests (L241–319)
- **L242–253:** Returns `{ supported: true }` when `dlv dap --help` exits 0.
- **L255–266:** Returns `{ supported: false }` when exit code is 1.
- **L268–280:** Returns `{ supported: false, stderr: 'spawn failed' }` on spawn error.
- **L282–299:** Verifies stderr **secret redaction** — lines containing tokens like `GITHUB_PAT=github_pat_...` are replaced with `'[REDACTED — line contained sensitive data]'` while safe lines like `'usage: dlv dap'` pass through.
- **L301–318:** Verifies stderr is **capped to last 10 lines** from 25-line output, with a `'(last 10 of 25 lines)'` prefix in the result.

### `getGoSearchPaths` tests (L321–352)
Uses `describe.each(['win32', 'linux', 'darwin'])` (L322) with `vi.stubGlobal('process', ...)` to test all platforms.
- **L331–343:** Asserts non-empty array; win32 paths include `C:\`, darwin paths include `/usr/local/go` or `homebrew`, linux paths include `/usr/`.
- **L345–350:** When `GOBIN` env is set to `/custom/gobin`, it appears as `paths[0]` (first element).

---

## Key Patterns
- **Async subprocess simulation:** `EventEmitter` with `.stdout`/`.stderr` sub-emitters and `process.nextTick` deferred emissions (L134–143, etc.) — mirrors Node.js `ChildProcess` interface.
- **Platform isolation:** `findGoExecutable`/`findDelveExecutable` tests avoid cross-platform mocking; `getGoSearchPaths` uses `vi.stubGlobal` for platform iteration.
- **Env stubbing:** `vi.stubEnv` used for `PATH`, `HOME`, `USERPROFILE`, `GOPATH`, `GOBIN` — all restored by `vi.unstubAllGlobals()` in `afterEach`.
- **Security behavior coverage:** `checkDelveDapSupport` has explicit tests for secret redaction and output truncation — these are behavioral contracts, not just correctness checks.
