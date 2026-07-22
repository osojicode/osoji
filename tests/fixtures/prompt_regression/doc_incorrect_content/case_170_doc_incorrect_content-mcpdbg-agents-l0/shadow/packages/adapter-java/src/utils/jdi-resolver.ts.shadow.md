# packages\adapter-java\src\utils\jdi-resolver.ts
@source-hash: 5f38b027c792fb5d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:29Z

## Purpose
Resolves and on-demand compiles the JDI bridge Java class (`JdiDapServer.class`) required by the adapter. Handles multiple deployment layouts (source, dist, workspace) and performs staleness checks to trigger recompilation when the `.java` source is newer than the cached `.class`.

---

## Key Symbols

### `resolveJdiBridgeClassDir()` (L20–50) — **exported**
Searches four candidate paths for the compiled `JdiDapServer.class` output directory:
1. `../../java/out` — TypeScript source (ts-node / vitest)
2. `../java/out` — compiled `dist/`
3. `../../../../packages/adapter-java/java/out` — compiled workspace dist
4. `process.cwd()/packages/adapter-java/java/out` — CWD fallback

**Environment override:** If `JDI_BRIDGE_DIR` env var is set, it is checked first (L33–37); returns early if `JdiDapServer.class` exists there. Returns `string` (absolute path to output dir) or `null` if no candidate resolves.

---

### `resolveJdiBridgeSourceDir()` (L55–74) — **internal**
Mirrors `resolveJdiBridgeClassDir` but searches for `JdiDapServer.java` in `java/` directories (without the `out/` suffix). Same four candidate layout strategies. Returns `string | null`.

---

### `ensureJdiBridgeCompiled()` (L84–130) — **exported**
Orchestrates compile-on-demand logic:
1. Resolves source dir and source file path (L86–87).
2. Calls `resolveJdiBridgeClassDir()` to check for existing compiled output (L90).
3. If already compiled and not stale (via `isClassStale`), returns immediately (L91–93).
4. Locates `javac`:
   - First tries `$JAVA_HOME/bin/javac[.exe]` (L101–106).
   - Falls back to `which javac` / `where javac` depending on platform (L108–116).
   - Returns `null` if `javac` not found (L117).
5. Compiles with `javac --release 21 JdiDapServer.java -d out/` via `execFileSync` (L122–125).
6. Returns output directory path on success, `null` on any failure.

---

### `isClassStale(sourceFile, classDir)` (L137–146) — **internal**
Compares `mtimeMs` of `JdiDapServer.java` vs `JdiDapServer.class`. Returns `true` if source is newer (triggers recompile). Stat failures return `false` (treat as "not stale", protecting known-good cached classes).

---

## Module-level Initialization (L12–13)
ESM-compatible `__filename` / `__dirname` emulation using `fileURLToPath(import.meta.url)` — required because this is an ES module (no CommonJS `__dirname`).

---

## Dependencies
- `fs`: `existsSync`, `mkdirSync`, `statSync` — filesystem presence checks, directory creation, mtime comparison
- `path`: path resolution and joining
- `url`: `fileURLToPath` for ESM `__dirname` emulation
- `child_process`: `execFileSync` (javac compilation), `execSync` (javac discovery via `which`/`where`)

---

## Architecture Notes
- **No external dependencies** — pure Node.js stdlib.
- **Staleness check** prevents silent bugs from stale class caches (e.g., missing `--owner-pid` CLI arg in older compiled versions).
- **Environment override** (`JDI_BRIDGE_DIR`) is checked before path scanning, enabling CI/CD injection.
- **Java 21 target** hardcoded via `--release 21` flag (L122).
- Candidate path list duplicated between `resolveJdiBridgeClassDir` and `resolveJdiBridgeSourceDir` — the two lists are parallel but independently maintained.