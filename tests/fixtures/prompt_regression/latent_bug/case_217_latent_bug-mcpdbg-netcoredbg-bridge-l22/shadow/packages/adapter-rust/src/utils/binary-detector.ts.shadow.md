# packages\adapter-rust\src\utils\binary-detector.ts
@source-hash: 90e21bd7d61a24ee
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:31Z

## Binary Format Detector for Rust Adapter

Analyzes Windows PE binaries to determine whether they were compiled with MSVC or GNU toolchains by scanning file headers, import tables, debug info markers, and adjacent PDB files.

### Purpose
Heuristically classifies a binary executable's toolchain format (`msvc` | `gnu` | `unknown`) and debug info type (`pdb` | `dwarf` | `none`) by reading up to 1MB of the binary's bytes and checking for known signatures/imports.

---

### Exported Interface

#### `BinaryInfo` (L4–10)
Result shape returned by `detectBinaryFormat`:
- `format`: `'msvc' | 'gnu' | 'unknown'` — toolchain classification
- `hasPDB`: boolean — whether a sibling `.pdb` file exists on disk
- `hasRSDS`: boolean — whether the `RSDS` debug signature appears in the binary bytes
- `imports`: `string[]` — matched known DLL import strings found in the binary
- `debugInfoType?`: `'pdb' | 'dwarf' | 'none'` — resolved debug info type

---

### Exported Function

#### `detectBinaryFormat(exePath)` (L64–109)
Async entry point. Pipeline:
1. `fs.stat(exePath)` — verifies path is a regular file; returns default `info` if not
2. Checks for sibling `<basename>.pdb` file → sets `info.hasPDB` (L79–90)
3. Reads up to `MAX_SCAN_BYTES` (1MB, L12) of the binary into a `Buffer` (L92–99)
4. Scans buffer for `RSDS` signature → `info.hasRSDS` (L101)
5. `collectImports(buffer)` → `info.imports` (L102)
6. `detectDebugInfo(buffer, hasPDB, hasRSDS)` → `info.debugInfoType` (L103)
7. `classifyFormat(imports, debugInfoType)` → `info.format` (L104)
8. All outer errors are silently caught and return the default `info` object (L107–109)

---

### Internal Helpers

#### `bufferContains(haystack, needle)` (L18–20)
Simple `Buffer.indexOf` wrapper; checks for `RSDS` signature presence.

#### `collectImports(buffer)` (L22–33)
Converts buffer to ASCII lowercase, then searches for any of the known MSVC/GNU DLL names:
- MSVC: `vcruntime140.dll`, `ucrtbase.dll`, `msvcp140.dll` (L15)
- GNU: `msvcrt.dll`, `libstdc++`, `libgcc` (L16)
Returns deduplicated matches as an array.

#### `detectDebugInfo(buffer, hasPDB, hasRSDS)` (L35–46)
Returns `'pdb'` if `hasPDB || hasRSDS`; checks buffer for DWARF hints (`.debug_info`, `dwarf`) → `'dwarf'`; otherwise `'none'`.

#### `classifyFormat(imports, debugInfoType)` (L48–62)
Priority order:
1. Any MSVC import present → `'msvc'`
2. Any GNU import present OR `debugInfoType === 'dwarf'` → `'gnu'`
3. Otherwise → `'unknown'`

---

### Constants (L12–16)
| Constant | Value | Purpose |
|---|---|---|
| `MAX_SCAN_BYTES` | `1024 * 1024` | Max bytes read from binary |
| `RSDS_SIGNATURE` | `Buffer('RSDS', 'ascii')` | PDB debug record signature |
| `DWARF_HINTS` | `['.debug_info', 'dwarf']` | DWARF section name hints |
| `MSVC_IMPORTS` | 3 DLL names | MSVC CRT/STL DLLs |
| `GNU_IMPORTS` | 3 DLL/lib names | GNU runtime libs |

---

### Architectural Notes
- Detection is heuristic/substring-based, not a full PE parser — intentionally lightweight
- All failures (stat errors, read errors, permission errors) are silently swallowed; callers always get a valid `BinaryInfo` with defaults
- The `hasMSVCImport` check (L50) lowercases the already-lowercased imports list for redundant but harmless safety
- `collectImports` uses `ascii.includes(dll.toLowerCase())` but DLL constants are already lowercase — no practical issue
