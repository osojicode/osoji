# scripts\setup\windows-rust-debug.ps1
@source-hash: 512d768210e85047
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:49Z

## Purpose
PowerShell setup script that provisions a Windows machine for Rust debugging with `mcp-debugger`. Installs Rust toolchains via rustup, configures `dlltool.exe` (preferring MSYS2 MinGW over rustup's self-contained copy), builds bundled Rust example projects, and optionally runs the Rust smoke test suite.

## Entry Point & Parameters (L23–28)
- `[switch]$UpdateUserPath` — If set, permanently writes PATH/DLLTOOL to the user environment registry; otherwise session-only.
- `[switch]$SkipBuild` — Skips building the `hello_world` and `async_example` Rust projects.
- `[switch]$SkipTests` — Skips running `vitest`-based Rust smoke tests via `pnpm`.

Script runs with `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'` (L30–31), meaning unhandled errors terminate execution.

## Key Functions

### `Write-Section` (L33–37)
Prints a cyan-colored section header with `===` prefix. Purely cosmetic.

### `Invoke-CommandChecked` (L39–74)
Core subprocess runner. Accepts `$Command`, `$Arguments[]`, `$EnvVars` hashtable, and `$WorkingDirectory`. Launches via `System.Diagnostics.ProcessStartInfo` with I/O redirected. Throws on non-zero exit code (L68–70). Arguments containing whitespace are automatically quoted (L50–56). Output is printed if non-empty (L71–73).

### `Get-Msys2Root` (L81–91)
Probes for MSYS2 installation root. Checks `$env:MSYS2_ROOT`, then `C:\msys64`, then `C:\tools\msys64` (L83–84). Returns resolved path or `$null`.

### `Install-Msys2ViaWinget` (L93–105)
Attempts to install MSYS2 via `winget install --id MSYS2.MSYS2`. Throws if `winget` is not available (L95–97).

### `Ensure-Msys2` (L107–117)
Calls `Get-Msys2Root`; if not found, calls `Install-Msys2ViaWinget` then rechecks. Throws if still not found. Returns resolved MSYS2 root path.

### `Test-MingwTools` (L119–134)
Validates presence of four required MinGW tools: `x86_64-w64-mingw32-gcc`, `ld`, `as`, `dlltool` (L124). Throws if any `.exe` is missing. Runs `--version` checks on gcc and dlltool via `Invoke-CommandChecked`.

### `Ensure-MingwToolchain` (L136–156)
Orchestrates MSYS2 + MinGW-w64 setup. Verifies `bash.exe` exists, installs `base-devel mingw-w64-x86_64-toolchain` via pacman if gcc is absent (L146–147), validates `dlltool.exe` exists, calls `Test-MingwTools`, and returns `$mingwBin` (`<msysRoot>\mingw64\bin`).

### `Ensure-PathEntry` (L158–189)
Prepends a directory to `$env:PATH` for the current session (case-insensitive dedup, L173–175). If `-Persist` is set, also appends to the user-level `Path` environment variable via `[System.Environment]::SetEnvironmentVariable` (L185).

### `Build-ExampleProject` (L191–229)
Builds a named Rust project by manifest path. Tries `cargo +stable-gnu build --target x86_64-pc-windows-gnu` first with `DLLTOOL` and `PATH` env vars forwarded (L203–208). On failure, falls back to `cargo +stable-msvc build --target x86_64-pc-windows-msvc` (L220–225). Both failures are non-fatal warnings.

## Main Execution Flow (L231–302)

1. **Prerequisites check** (L231–240): Verifies `rustup` is on PATH. Installs `stable-gnu` and `stable-msvc` toolchains with minimal profile. Sets default to `stable-gnu`. Adds `x86_64-pc-windows-gnu` target.

2. **dlltool baseline** (L242–246): Constructs expected path for rustup's self-contained `dlltool.exe` under `$env:USERPROFILE\.rustup\toolchains\stable-x86_64-pc-windows-gnu\...\self-contained\`. Throws if not found.

3. **MSYS2 preference** (L251–261): Attempts `Ensure-MingwToolchain`; on success, upgrades `$preferredDlltool` to the MSYS2 version and adds MinGW bin to PATH. On failure, falls back silently to rustup's copy with a warning.

4. **Environment configuration** (L263–274): Sets `$env:DLLTOOL` to `$preferredDlltool`. If `-UpdateUserPath`, also sets user-level `DLLTOOL` env var persistently.

5. **Build examples** (L276–285): Unless `-SkipBuild`, calls `Build-ExampleProject` for `hello_world` and `async_example` from `../../examples/rust/`.

6. **Smoke tests** (L287–299): Unless `-SkipTests`, runs `pnpm vitest run tests/e2e/mcp-server-smoke-rust.test.ts`. Warns if `pnpm` is absent.

## Notable Patterns & Constraints
- MSYS2 MinGW `dlltool.exe` is *preferred* over rustup's copy when available, but rustup's is used as fallback.
- `Build-ExampleProject` always forwards the current session's `DLLTOOL` and `PATH` to cargo, ensuring the configured dlltool is used.
- Argument quoting in `Invoke-CommandChecked` uses `Join` into a single string rather than an array, which can break with complex arguments containing mixed quotes.
- Script is Windows-only (enforced at L76–79 via `RuntimeInformation.IsOSPlatform`).
- `Ensure-PathEntry` prepends (not appends) to `$env:PATH` at L174, so the new directory takes priority over existing entries.
- The persistent user PATH append (L184) appends to the end, giving it *lower* priority than system entries — opposite behavior to the session prepend.