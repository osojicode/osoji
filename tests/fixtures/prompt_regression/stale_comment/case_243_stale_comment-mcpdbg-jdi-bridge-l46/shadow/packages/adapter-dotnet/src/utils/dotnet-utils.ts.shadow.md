# packages\adapter-dotnet\src\utils\dotnet-utils.ts
@source-hash: 713a4ddfeb5d1702
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:58Z

## Purpose

Utilities for the `.NET` debug adapter: locating the `netcoredbg` debugger executable with architecture awareness, inspecting running Windows processes via WMIC/tasklist, reading PE and PDB binary headers, and converting Windows-format PDBs to Portable PDB format using `Pdb2Pdb.exe`.

---

## Key Symbols

### `CommandNotFoundError` (L41–48)
Custom `Error` subclass. Sets `this.name = 'CommandNotFoundError'` and stores the missing command in `this.command`. Thrown by `findNetcoredbgExecutable` when no binary is found.

### `findNetcoredbgExecutable` (L64–153) — `async`
Locates the `netcoredbg` binary with 6-step priority cascade:
1. `NETCOREDBG_X86_PATH` env var (only when `targetArch === 'x86'`)
2. `NETCOREDBG_PATH` env var (with optional arch check via `getExeArchitecture`)
3. `preferredPath` argument (with optional arch check)
4. `which('netcoredbg')` — skipped when `targetArch` is set
5. `getNetcoredbgSearchPaths(targetArch)` candidate list
6. Recursive call without `targetArch` if arch-specific search failed (L147)

Throws `CommandNotFoundError` if nothing is found.

Parameters: `preferredPath?` (string), `logger` (Logger, default `noopLogger`), `targetArch?` (`'x86' | 'x64'`).

### `getNetcoredbgSearchPaths` (L158–188) — internal
Returns platform-specific filesystem candidate paths. On `win32`, prepends x86-specific paths when `targetArch === 'x86'`. On other platforms returns standard Linux/macOS locations.

### `findDotnetBackend` (L196–201) — `async`
Thin wrapper around `findNetcoredbgExecutable(undefined, logger)`. Returns `{ backend: 'netcoredbg', path: string }`.

### `listDotnetProcesses` (L209–264) — `async`
Windows-only. Spawns `tasklist /FO CSV /NH`, parses CSV output, and filters for a hardcoded list of known .NET process names (`ninjatrader.exe`, `devenv.exe`, `dotnet.exe`, `w3wp.exe`, `iisexpress.exe`). Returns `[]` on non-Windows or on error.

### `getProcessExecutablePath` (L273–299)
Windows-only. Uses `spawnSync('wmic', ...)` with a 5-second timeout to query `ExecutablePath` for a given PID. Parses `ExecutablePath=<value>` from WMIC output. Returns `null` on non-Windows, failure, or missing output.

### `getProcessExecutableDir` (L308–311)
Convenience wrapper: calls `getProcessExecutablePath` and returns `path.dirname(exePath)` or `null`.

### `getExeArchitecture` (L319–348)
Reads PE binary header from a file descriptor:
- Reads 4 bytes at offset `0x3C` for PE header offset
- Reads 6 bytes at `peOffset` to verify `PE\0\0` signature and extract `Machine` field
- Returns `'x86'` for machine `0x014c` (IMAGE_FILE_MACHINE_I386), `'x64'` for `0x8664` (IMAGE_FILE_MACHINE_AMD64), `null` otherwise or on error.

### `isPortablePdb` (L371–386)
Reads first 4 bytes of a PDB file and checks for Portable PDB magic `BSJB` (`0x42 0x53 0x4A 0x42`). Returns `false` on error or insufficient bytes.

### `findPdb2PdbExecutable` (L398–420)
Locates `Pdb2Pdb.exe` in priority order:
1. `PDB2PDB_PATH` env var
2. Bundled at `../../tools/pdb2pdb/Pdb2Pdb.exe` relative to this compiled file (uses `import.meta.url`)
3. Fallback at `/tmp/pdb2pdb-tool/Pdb2Pdb.exe`

Returns `null` if none found.

### `convertPdbsToTemp` (L432–501)
Scans `sourceDirs` for `.pdb` files, skips Portable PDBs, requires a matching `.dll`, copies both to a timestamped temp directory (`mcp-debugger-pdbs-<timestamp>`), then runs `Pdb2Pdb.exe <dll>` synchronously with 30-second timeout. Renames `<name>.pdb2` output to `<name>.pdb`. Returns temp directory path if ≥1 conversion succeeded, otherwise `null`.

---

## Internal Interfaces

### `Logger` (L31–34)
`{ error: (message: string) => void; debug?: (message: string) => void }` — optional debug logging abstraction.

### `noopLogger` (L36–39)
Default `Logger` implementation with no-op functions; used as default parameter throughout.

---

## Architecture Notes

- **PE header parsing** is done directly with Node `fs` file descriptors — no native addons needed.
- **PDB conversion** uses a copy-to-temp strategy to avoid file-lock conflicts with the debuggee process.
- **x86 targeting** triggers architecture validation at every resolution step; falls back to any-arch if no x86 binary found.
- `findDotnetBackend` always passes `undefined` for `preferredPath` and `targetArch` — it only supports generic (non-arch-specific) discovery.
- `import.meta.url` usage (L407) means this file must be run as an ES module.
