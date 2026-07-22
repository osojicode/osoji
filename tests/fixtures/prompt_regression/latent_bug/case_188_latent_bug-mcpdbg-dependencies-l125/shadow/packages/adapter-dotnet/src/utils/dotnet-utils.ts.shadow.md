# packages\adapter-dotnet\src\utils\dotnet-utils.ts
@source-hash: 713a4ddfeb5d1702
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:47Z

## Purpose
Utility module for the .NET debugger adapter providing: netcoredbg executable discovery (with architecture-aware fallback), Windows PDB→Portable PDB conversion via Pdb2Pdb.exe, .NET process enumeration, and PE executable architecture detection.

## Key Exports

### `CommandNotFoundError` (L41-48)
Custom `Error` subclass thrown when netcoredbg cannot be found. Carries `command: string` field and `name = 'CommandNotFoundError'` for discrimination.

### `findNetcoredbgExecutable(preferredPath?, logger?, targetArch?)` (L64-153)
Async. Resolves the netcoredbg binary path using a 6-step priority chain:
1. `NETCOREDBG_X86_PATH` env var (x86 target only)
2. `NETCOREDBG_PATH` env var (with arch validation for x86)
3. User-supplied `preferredPath`
4. `which('netcoredbg')` — skipped when `targetArch` is specified
5. `getNetcoredbgSearchPaths(targetArch)` common installation locations
6. Recursive fallback to arch-agnostic search if arch-specific search fails

Throws `CommandNotFoundError` if not found. Validates PE architecture via `getExeArchitecture` for x86 targets.

### `findDotnetBackend(logger?)` (L196-201)
Thin wrapper around `findNetcoredbgExecutable` returning `{ backend: 'netcoredbg', path: string }`.

### `listDotnetProcesses(logger?, platform?)` (L209-264)
Async. Windows-only — returns `[]` on non-win32 platforms. Runs `tasklist /FO CSV /NH` via `spawn`, parses CSV output, filters against a hardcoded known-dotnet-processes list: `ninjatrader.exe`, `devenv.exe`, `dotnet.exe`, `w3wp.exe`, `iisexpress.exe`.

### `getProcessExecutablePath(pid, platform?)` (L273-299)
Sync. Windows-only. Uses `spawnSync('wmic', ...)` to resolve full exe path from PID. Returns `null` on non-win32 or failure.

### `getProcessExecutableDir(pid, platform?)` (L308-311)
Wraps `getProcessExecutablePath`; returns `path.dirname(exePath)` or `null`.

### `getExeArchitecture(exePath)` (L319-348)
Reads the PE Machine header field directly from file bytes. Returns `'x86'` (Machine=0x014c), `'x64'` (Machine=0x8664), or `null`. Validates PE signature `"PE\0\0"` before reading Machine field.

### `getProcessArchitecture(pid, platform?)` (L356-360)
Combines `getProcessExecutablePath` + `getExeArchitecture`. Returns `'x86'`/`'x64'`/`null`.

### `isPortablePdb(pdbPath)` (L371-386)
Checks for Portable PDB magic bytes `"BSJB"` (0x42 0x53 0x4A 0x42) at file offset 0. Returns `false` on Windows PDB or read error.

### `findPdb2PdbExecutable()` (L398-420)
Priority: `PDB2PDB_PATH` env var → bundled at `../../tools/pdb2pdb/Pdb2Pdb.exe` relative to this file (resolved via `fileURLToPath(import.meta.url)`) → `/tmp/pdb2pdb-tool/Pdb2Pdb.exe`. Returns `null` if none found.

### `convertPdbsToTemp(sourceDirs, pdb2pdbPath)` (L432-501)
Scans each directory for `.pdb` files, skips Portable PDBs, requires matching `.dll` sibling. Copies DLL+PDB pair to a temp dir (`mcp-debugger-pdbs-<timestamp>` under `os.tmpdir()`), runs `Pdb2Pdb.exe <dll>`. Handles two Pdb2Pdb output conventions: `.pdb2` output file (rename to `.pdb`) or in-place overwrite. Returns temp dir path if ≥1 conversion succeeded, else `null`.

## Internal Helpers

### `noopLogger` (L36-39)
Default logger with no-op `error` and `debug` callbacks. Used as default parameter in all exported functions.

### `getNetcoredbgSearchPaths(targetArch?)` (L158-188)
Returns platform-specific candidate paths. Windows: checks `USERPROFILE/documents/github/netcoredbg/`, `C:\netcoredbg\`, etc. (x86 variants prepended for x86 targets). Non-Windows: `/usr/local/bin/`, `/usr/bin/`, `/opt/netcoredbg/`, `~/netcoredbg/`.

## Architecture Patterns
- **Copy-to-temp PDB strategy**: avoids file-lock conflicts with running debuggee (L433)
- **PE header parsing**: direct binary read at fixed offsets, no native bindings needed (L321-347)
- **Progressive fallback**: arch-specific search degrades gracefully to arch-agnostic (L145-148)
- **Platform injection**: `platform` parameter (defaulting to `process.platform`) on process-listing/arch functions enables testability without mocking globals

## Key Constraints
- PDB conversion requires matching `.dll` to exist alongside `.pdb` (Pdb2Pdb.exe requires the PE binary)
- `listDotnetProcesses` / `getProcessExecutablePath` / `getProcessArchitecture` are Windows-only
- `findPdb2PdbExecutable` fallback `/tmp/pdb2pdb-tool/Pdb2Pdb.exe` is POSIX-only path (L414)