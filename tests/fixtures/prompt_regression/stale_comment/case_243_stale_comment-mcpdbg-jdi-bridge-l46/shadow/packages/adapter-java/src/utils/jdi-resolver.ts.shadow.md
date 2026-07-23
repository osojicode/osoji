# packages\adapter-java\src\utils\jdi-resolver.ts
@source-hash: 5f38b027c792fb5d
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:12Z

## Purpose
Resolves and compiles the JDI (Java Debug Interface) bridge class (`JdiDapServer.java`) for use by the adapter. Handles multi-environment path resolution, staleness detection, and on-demand `javac` compilation.

## Key Symbols

### `resolveJdiBridgeClassDir()` (L20–50) — **public**
Searches 4 candidate directories (plus `JDI_BRIDGE_DIR` env override) for a compiled `JdiDapServer.class`. Returns the absolute path of the first match, or `null`.

**Search order:**
1. `JDI_BRIDGE_DIR` env var (checked first, before candidates)
2. `../../java/out` (ts-node / vitest from source)
3. `../java/out` (compiled dist/)
4. `../../../../packages/adapter-java/java/out` (workspace dist)
5. `<cwd>/packages/adapter-java/java/out` (CWD fallback)

### `resolveJdiBridgeSourceDir()` (L55–74) — **internal**
Mirrors `resolveJdiBridgeClassDir` search strategy but looks for `JdiDapServer.java` (source). No env override. Returns source directory or `null`.

### `ensureJdiBridgeCompiled()` (L84–130) — **public**
Orchestrates compilation:
1. Resolves source dir → constructs `sourceFile` path (L86–87)
2. Checks existing compiled class, returns early if not stale (L90–93)
3. If no source found, returns `null` (L95)
4. Locates `javac` via `JAVA_HOME` env or `which`/`where` (L100–116)
5. Compiles with `--release 21` into `<sourceDir>/out` (L120–129)
6. Returns `outDir` on success, `null` on any failure

### `isClassStale(sourceFile, classDir)` (L137–145) — **internal**
Compares `mtimeMs` of `JdiDapServer.java` vs `JdiDapServer.class`. Returns `true` if source is newer. Stat failures return `false` (safe default: don't rebuild against unknown cached class).

## Module-Level Setup (L12–13)
ESM-compatible `__filename`/`__dirname` emulation using `fileURLToPath(import.meta.url)`.

## Dependencies
- `fs`: `existsSync`, `mkdirSync`, `statSync`
- `path`: path resolution
- `url`: `fileURLToPath` (ESM compat)
- `child_process`: `execFileSync` (javac), `execSync` (which/where)

## Key Design Decisions
- **Multi-candidate resolution**: tolerates ts-node, compiled, monorepo-dist, and CWD-relative invocations without configuration
- **`JDI_BRIDGE_DIR` env override**: only accepted if `JdiDapServer.class` physically exists within it
- **Staleness check**: prevents silent breakage when `.java` source is updated but `.class` is cached
- **Stat failures = not stale** (L143–144): conservative — avoids unnecessary recompile if source is inaccessible
- **`--release 21`** (L122): hardcoded Java 21 target

## Environment Variables
- `JDI_BRIDGE_DIR`: override class directory (checked before candidate paths)
- `JAVA_HOME`: used to locate `javac` binary (L101–106)
- `process.platform`: selects `javac.exe` vs `javac`, `where` vs `which`