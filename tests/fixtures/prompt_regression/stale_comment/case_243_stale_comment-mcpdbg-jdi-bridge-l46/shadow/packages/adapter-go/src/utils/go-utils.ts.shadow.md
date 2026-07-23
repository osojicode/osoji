# packages\adapter-go\src\utils\go-utils.ts
@source-hash: a592e80be738ced7
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:36Z

## Go/Delve Utility Functions

Provides executable discovery, version checking, and DAP support verification for Go and Delve (dlv) debugger binaries. Used by the adapter-go package to locate required toolchain components before launching debug sessions.

### Key Functions

**`findGoExecutable` (L20-58)** — Resolves the Go binary path via priority chain:
1. `preferredPath` if provided and executable-accessible
2. `go` / `go.exe` on system `PATH`
3. Platform-specific common install paths (via `getGoSearchPaths`)
Throws if not found.

**`findDelveExecutable` (L63-103)** — Resolves the `dlv` binary path via priority chain:
1. `preferredPath` if provided and executable-accessible
2. `dlv` / `dlv.exe` / `dlv-dap` / `dlv-dap.exe` on system `PATH`
3. `GOBIN` → `GOPATH/bin` → `~/go/bin` (via `getGopathBin`)
Throws if not found.

**`getGoVersion` (L108-128)** — Spawns `go version`, parses output regex `/go(\d+\.\d+(\.\d+)?)/`, returns semver string or `null`.

**`getDelveVersion` (L133-153)** — Spawns `dlv version`, parses output regex `/Version:\s*(\d+\.\d+\.\d+)/`, returns semver string or `null`.

**`checkDelveDapSupport` (L159-179)** — Spawns `dlv dap --help`; if exit code 0, DAP is supported. Captures stderr, sanitizes it via `sanitizeStderrTail` before including in result (to prevent raw stderr leaking into MCP tool responses).

**`getGoSearchPaths` (L184-217)** — Returns platform-specific Go binary search directories. On Windows: `C:\Go\bin`, `C:\Program Files\Go\bin`, `%USERPROFILE%\go\bin`, `%LOCALAPPDATA%\Programs\Go\bin`. On macOS: Homebrew paths, `/usr/local/go/bin`, `~/go/bin`. On Linux: `/usr/local/go/bin`, `/usr/bin`, `~/go/bin`. Prepends `GOBIN` if set.

### Internal Helpers

- **`getGopathBin` (L222-240)** — Returns binary directory: `GOBIN` > `GOPATH/bin` > `~/go/bin` > `null`.
- **`findInPath` (L245-258)** — Iterates `PATH` entries, checks executable access for each candidate.
- **`fileExists` (L263-270)** — Uses `fs.promises.access` with `X_OK` flag; returns boolean (not just existence, but execute permission).

### Logger Interface (L11-15)
All three optional methods (`debug`, `info`, `error`) are optional on the interface, called with optional chaining (`logger?.debug?.()`).

### Architectural Notes
- `fileExists` checks `X_OK` (execute permission), not just file existence — appropriate for binary discovery but may return `false` on Windows for valid executables where execute semantics differ.
- `dlv-dap` variant candidates are checked in `findDelveExecutable` but `getGopathBin` fallback only checks `dlv`/`dlv.exe`, not `dlv-dap`.
- stderr from `checkDelveDapSupport` is sanitized via `sanitizeStderrTail` from `@debugmcp/shared` before surfacing to callers.
