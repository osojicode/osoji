# tests\adapters\java\unit\jdi-resolver.test.ts
@source-hash: 4eebe4dd489dc7d2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:42Z

## Unit Tests: `jdi-resolver` (JDI Bridge Class Resolution & Compilation)

Tests the `resolveJdiBridgeClassDir` and `ensureJdiBridgeCompiled` functions exported from `@debugmcp/adapter-java`. These functions handle locating pre-compiled JDI bridge `.class` files and triggering on-demand `javac` compilation when needed.

### Module-level Mocking (L5–31)
- **`fs` mock** (L5–12): Replaces `existsSync` and `mkdirSync` with `vi.fn()` stubs, spreading the real module for all other exports.
- **`child_process` mock** (L15–22): Replaces `execSync` and `execFileSync` with `vi.fn()` stubs.
- **Typed mock refs** (L28–31): `mockExistsSync`, `mockMkdirSync`, `mockExecSync`, `mockExecFileSync` — used throughout tests for configuring behavior and asserting calls.

### `beforeEach` (L34–38)
Clears all mocks and sets `mockExistsSync` to return `false` by default (nothing exists).

---

### `resolveJdiBridgeClassDir` Tests (L40–92)

| Test | Scenario | Expected |
|---|---|---|
| L41–49 | `JDI_BRIDGE_DIR` env set, `JdiDapServer.class` exists there | Returns env var path |
| L51–57 | `JDI_BRIDGE_DIR` set but class absent | Returns `null` |
| L59–73 | No env var; class found via candidate path search matching `java/out/JdiDapServer.class` | Returns non-null path containing `"java"` and `"out"` |
| L75–81 | No env var; class absent everywhere | Returns `null` |
| L83–91 | `existsSync` throws | Returns `null` (graceful error handling) |

Key: The function checks `JDI_BRIDGE_DIR` env var first, then searches candidate relative paths. Class existence confirmed by looking for `JdiDapServer.class`.

---

### `ensureJdiBridgeCompiled` Tests (L94–218)

| Test | Scenario | Expected |
|---|---|---|
| L95–105 | Class already compiled (`JdiDapServer.class` exists) | Returns path, does NOT call `execFileSync` |
| L107–113 | No class, no source | Returns `null` |
| L115–134 | No class; source exists; `JAVA_HOME=/usr/lib/jvm/java-21`; javac found via JAVA_HOME | Calls `mkdirSync` + `execFileSync` |
| L136–155 | No class; source exists; no `JAVA_HOME`; `execSync` (which) returns `/usr/bin/javac` | Calls `execSync` then `execFileSync` |
| L157–174 | Source exists; no `JAVA_HOME`; `execSync` throws (javac not on PATH) | Returns `null` |
| L176–194 | Source + JAVA_HOME javac found; `execFileSync` throws | Returns `null` |
| L196–217 | Full happy path with JAVA_HOME | `execFileSync` called with args including `javac`, `--release`, `21` |

Key compilation contract (L212–216):
- `execFileSync` called with: `(path containing "javac", array containing ['--release', '21'], options object)`
- `mkdirSync` called before compilation to ensure output directory exists.
- `javac` resolution priority: `JAVA_HOME/bin/javac` → PATH via `which`/`execSync`.

---

### Dependencies
- `@debugmcp/adapter-java`: Source under test — exports `resolveJdiBridgeClassDir` and `ensureJdiBridgeCompiled` (L26)
- `fs`: `existsSync`, `mkdirSync` — mocked
- `child_process`: `execSync` (for `which javac`), `execFileSync` (for compilation invocation) — mocked
- `path`: Used to construct platform-correct path assertions in tests (L44, L64)

### Key Behavioral Contracts Verified
1. `JDI_BRIDGE_DIR` env var takes priority in class resolution.
2. Graceful null returns on any failure path (missing source, missing javac, compilation error, fs exceptions).
3. Java release target is `21` (`--release 21`).
4. Output directory is created with `mkdirSync` before compilation.
5. `execSync` is used only for PATH-based javac discovery; `execFileSync` is used for the actual compile invocation.
