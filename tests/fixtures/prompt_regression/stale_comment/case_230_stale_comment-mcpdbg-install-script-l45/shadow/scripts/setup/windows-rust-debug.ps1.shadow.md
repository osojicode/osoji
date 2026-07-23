# scripts\setup\windows-rust-debug.ps1
@source-hash: 2d363ffea961bae2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:31Z

## Purpose
PowerShell setup script that configures a Windows machine for Rust debugging with mcp-debugger. Installs/verifies Rust toolchains (`stable-gnu`, `stable-msvc`), provisions MSYS2 + MinGW-w64, resolves the preferred `dlltool.exe`, optionally persists PATH/env changes, builds bundled Rust example projects, and optionally runs smoke tests.

## Parameters (L25–29)
- `$UpdateUserPath` [switch]: Persists PATH and `DLLTOOL` env var to the user environment. Without it, changes apply to current session only.
- `$SkipBuild` [switch]: Skips building the bundled Rust examples.
- `$SkipTests` [switch]: Skips running the vitest Rust smoke tests.

## Script-level Config (L31–32)
- `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'` — strict error handling throughout.

## Key Functions

### `Write-Section` (L34–38)
Simple section header printer using cyan color. Takes a `$message` string.

### `Invoke-CommandChecked` (L40–75)
Core process runner. Launches an external command via `System.Diagnostics.ProcessStartInfo`, captures stdout/stderr, and throws on non-zero exit code. Supports injecting env vars and setting a working directory. Quotes arguments with whitespace. **Note:** stdout is printed after process exits; stderr is only shown on failure.

### `Get-Msys2Root` (L82–92)
Discovers MSYS2 root directory. Checks `$env:MSYS2_ROOT` first, then `C:\msys64`, then `C:\tools\msys64`. Returns resolved path or `$null`.

### `Install-Msys2ViaWinget` (L94–106)
Installs MSYS2 via `winget install --id MSYS2.MSYS2`. Throws if `winget` is not available.

### `Ensure-Msys2` (L108–118)
Calls `Get-Msys2Root`; if not found, calls `Install-Msys2ViaWinget` and rechecks. Throws if still not found after install attempt.

### `Test-MingwTools` (L120–135)
Validates that `x86_64-w64-mingw32-gcc`, `ld`, `as`, and `dlltool` executables exist in the specified `$BinDir`. Verifies gcc and dlltool by running `--version`.

### `Ensure-MingwToolchain` (L137–157)
Orchestrates MSYS2 + MinGW-w64 setup. Calls `Ensure-Msys2`, uses `bash.exe -lc` to run `pacman` if `x86_64-w64-mingw32-gcc.exe` is absent. Calls `Test-MingwTools` to validate. Returns `$mingwBin` path (`<msysRoot>\mingw64\bin`).

### `Ensure-PathEntry` (L159–190)
Idempotently prepends a directory to the current session's `$env:PATH`. With `-Persist`, also appends to the user-level PATH via `[System.Environment]::SetEnvironmentVariable`. Case-insensitive deduplication.

### `Build-ExampleProject` (L192–230)
Builds a Rust project at `$ManifestPath` with `$Name`. Attempts `cargo +stable-gnu build --target x86_64-pc-windows-gnu` first (passing `DLLTOOL` and `PATH` env vars). Falls back to `cargo +stable-msvc build --target x86_64-pc-windows-msvc` on failure. Warnings are emitted on failure; script does not abort.

## Top-Level Script Execution Flow (L232–303)

1. **Prerequisites check** (L232–241): Verifies `rustup`, installs `stable-gnu` and `stable-msvc` toolchains (minimal profile), sets default to `stable-gnu`, adds `x86_64-pc-windows-gnu` target.

2. **dlltool fallback location** (L243–247): Constructs expected rustup self-contained `dlltool.exe` path at `$env:USERPROFILE\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained\dlltool.exe`. Throws if not found.

3. **dlltool selection** (L249–262): Attempts to provision MSYS2/MinGW toolchain. On success, overrides `$preferredDlltool` with MSYS2's `dlltool.exe`. On failure, warns and keeps rustup fallback. MSYS2 failure is non-fatal.

4. **PATH/env propagation** (L264–275): Sets `$env:DLLTOOL` for the session. Adds parent dir of preferred dlltool to PATH. If `-UpdateUserPath`, persists both `DLLTOOL` env var and PATH persistently to the user scope.

5. **Build examples** (L277–286): Unless `-SkipBuild`, builds `hello_world` and `async_example` from `../../examples/rust/` relative to the script location.

6. **Smoke tests** (L288–300): Unless `-SkipTests`, runs `pnpm vitest run tests/e2e/mcp-server-smoke-rust.test.ts`. Requires `pnpm` on PATH; warns if absent; warns (non-fatal) on test failure.

## dlltool Priority Logic
- Primary: MSYS2 MinGW64 (`<msysRoot>\mingw64\bin\dlltool.exe`)
- Fallback: rustup self-contained (`~\.rustup\toolchains\stable-x86_64-pc-windows-gnu\...\self-contained\dlltool.exe`)

## Relative Paths Resolved at Runtime
- Examples resolved using `$PSScriptRoot` (L280–281): `..\..\examples\rust\hello_world\Cargo.toml`, `..\..\examples\rust\async_example\Cargo.toml`
- Script is located at `scripts\setup\windows-rust-debug.ps1`, so examples are at project root `examples\rust\`.

## Dependencies
- `rustup` (must be pre-installed)
- `winget` (optional; used for MSYS2 auto-install)
- `pnpm` + `vitest` (optional; used for smoke tests)
- `cargo` (via rustup)
- `bash.exe` from MSYS2 (for pacman invocation)
