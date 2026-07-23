# packages\adapter-java\scripts\compile-jdi-bridge.js
@source-hash: 9c01bd3a2536bf28
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:47Z

## Purpose
Build/setup script that compiles `JdiDapServer.java` into `java/out/JdiDapServer.class` using the system `javac`. Runs as a Node.js ESM script (shebang entry point), typically invoked as a `postinstall` or `prepare` npm lifecycle script for the `adapter-java` package.

## Key Constants (L19–23)
| Constant | Value (relative to script location) |
|---|---|
| `JAVA_DIR` | `../java` |
| `SOURCE_FILE` | `../java/JdiDapServer.java` |
| `OUT_DIR` | `../java/out` |
| `CLASS_FILE` | `../java/out/JdiDapServer.class` |
| `TARGET_RELEASE` | `21` (minimum JDK version required) |

## Key Functions

### `findJavac()` (L25–42)
Resolves the `javac` executable path. Resolution order:
1. `$JAVA_HOME/bin/javac[.exe]` (platform-aware, L28–29)
2. `which`/`where javac` on PATH (L34–36), returns first line of output

Returns `null` if `javac` is not found anywhere.

### `getJavacMajorVersion(javac)` (L44–56)
Runs `javac -version`, extracts major version integer via regex `/javac\s+(\d+)/`. Returns `null` on failure. Note: `javac -version` outputs to **stderr** in older JDKs, but the code captures both stdout and stderr (`stdio: ['ignore', 'pipe', 'pipe']`), so the combined output is checked against the regex.

### `needsCompilation()` (L58–65)
Incremental build check:
- Returns `true` if class file is missing
- Returns `false` if source file is missing (nothing to compile)
- Returns `true` if source `mtimeMs` > class `mtimeMs`

### `main()` (L67–122)
Orchestrates the full compile workflow:
1. **Skip guards** (L68–76): Exits early if `SKIP_JDI_COMPILE` (any truthy value) or `SKIP_ADAPTER_VENDOR=true` (case-insensitive, trimmed) env vars are set.
2. **Source check** (L78–81): Hard fails (`process.exit(1)`) if source file is missing.
3. **Up-to-date check** (L83–86): Skips if class is newer than source.
4. **javac discovery** (L88–94): Soft-fails (warn + return) if not found — adapter reports error at runtime.
5. **Version check** (L96–102): Soft-fails if `javacVersion < 21`.
6. **Compilation** (L104–121): Creates `OUT_DIR` recursively, invokes `javac --release 21 JdiDapServer.java -d java/out`. Hard fails (`process.exit(1)`) on javac error.

## Behavioral Notes
- **Graceful degradation**: Missing/old `javac` produces a warning but does NOT exit with error code. This is intentional — the adapter defers the error to runtime.
- **Hard failure cases**: Missing source file (L80) or javac compilation error (L120).
- **Cross-platform**: Handles Windows `javac.exe` and `where` vs Unix `which` (L28, L34).
- **ESM module**: Uses `import.meta.url` + `fileURLToPath` to emulate `__dirname` (L16–17).

## Environment Variables Consumed
| Variable | Behavior |
|---|---|
| `SKIP_JDI_COMPILE` | Any value → skip entirely |
| `SKIP_ADAPTER_VENDOR` | `"true"` (case-insensitive) → skip entirely |
| `JAVA_HOME` | Checked first for `javac` location |