# tests\e2e\java-example-utils.ts
@source-hash: f9a86dbd2004548e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## Java Example Fixture Builder for E2E Tests

Provides on-demand compilation of Java example programs for e2e tests, with mtime-based cache invalidation. Mirrors `tests/e2e/rust-example-utils.ts` in design. Ensures `.java` sources in `examples/java/` are compiled with `javac -g` (enabling `LocalVariableTable` for JDI) before tests reference the resulting `.class` files.

### Architecture

**Synchronous API (L8–9):** All calls occur inside test setup, not hot paths. Uses `execFileSync` to avoid asynchronous complexity.

**Module-level constants (L16–19):**
- `__filename` / `__dirname`: ESM-compatible path resolution via `fileURLToPath`
- `ROOT`: Two levels up from this file (`../../`)
- `JAVA_DIR`: Resolves to `<ROOT>/examples/java`

**Example registry `EXAMPLES` (L45–52):** `Record<JavaExampleName, JavaExampleSpec>` mapping each example name to its main class and optional extra source files. `EventRaceTest` is the only entry with `extraSources: ['LateLoadedHelper']`.

**Process-level cache `prepared` (L54):** `Map<JavaExampleName, JavaExamplePaths>` — prevents redundant rebuilds across test cases within a single test process run.

### Key Exported Symbols

**`JavaExampleName` (L21–27):** String literal union type — valid example names: `'HelloWorld'`, `'PauseTest'`, `'EventRaceTest'`, `'InnerClassTest'`, `'ExprTest'`, `'InfiniteWait'`.

**`JavaExamplePaths` (L29–36):** Interface returned by `prepareJavaExample`:
- `sourcePath`: Absolute path to main `.java` file
- `classDir`: Directory for `.class` output (always `JAVA_DIR`)
- `mainClass`: JVM entry point class name string

**`JavaExampleSpec` (L38–43):** Internal interface (not exported):
- `mainClass`: Source file basename and FQCN
- `extraSources?`: Additional source basenames co-compiled with main

**`prepareJavaExample(name)` (L61–94):** Main entry point for tests.
1. Looks up spec in `EXAMPLES`
2. Returns cached result if it exists AND `needsRebuild` returns false
3. Validates existence of all source files (throws `Error` if missing)
4. Runs `javac -g -d <JAVA_DIR> <allSources>` via `execFileSync`
5. Caches and returns `JavaExamplePaths`

**`needsRebuild(paths, spec)` (L96–108):** Internal helper.
- Returns `true` if `.class` file is missing
- Returns `true` if any source `.mtimeMs >= classMtime` (i.e., source is same age or newer)
- Catches `statSync` errors and returns `true` (safe fallback)

### Compilation Command

`javac -g -d <JAVA_DIR> [mainSource, ...extraSources]` — array-form args avoid shell parsing, ensuring paths with spaces work on Windows (L82–85).