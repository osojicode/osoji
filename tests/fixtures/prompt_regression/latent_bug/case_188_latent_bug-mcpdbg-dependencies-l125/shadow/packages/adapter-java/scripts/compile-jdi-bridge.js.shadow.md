# packages\adapter-java\scripts\compile-jdi-bridge.js
@source-hash: 9c01bd3a2536bf28
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## Purpose
Node.js build script (ESM) that compiles `JdiDapServer.java` into `java/out/` using the system `javac`. Acts as a pre-build step for the `adapter-java` package, replacing a previous `vendor-kotlin-debug-adapter.js` approach.

## Key Constants (L19–L24)
| Constant | Value |
|---|---|
| `JAVA_DIR` | `<package-root>/java/` |
| `SOURCE_FILE` | `<package-root>/java/JdiDapServer.java` |
| `OUT_DIR` | `<package-root>/java/out/` |
| `CLASS_FILE` | `<package-root>/java/out/JdiDapServer.class` |
| `TARGET_RELEASE` | `21` (minimum JDK version) |

## Key Functions

### `findJavac()` (L25–L42)
Resolves the `javac` executable path. Resolution order:
1. `$JAVA_HOME/bin/javac[.exe]` — checks `process.env.JAVA_HOME`, platform-aware extension
2. `where javac` / `which javac` — parses first line of output from PATH search

Returns absolute path string or `null` if not found.

### `getJavacMajorVersion(javac)` (L44–L56)
Runs `javac -version`, parses the major version number from output (e.g., `"javac 21.0.1"` → `21`). Returns `Number` or `null` on failure. Note: `javac -version` outputs to stderr on older JDKs but the implementation captures both stdout and stderr pipes — may miss version on pre-JDK-9 compilers.

### `needsCompilation()` (L58–L65)
Returns `true` if:
- `CLASS_FILE` does not exist, OR
- `SOURCE_FILE` mtime > `CLASS_FILE` mtime (source is newer than compiled output)

Returns `false` if source file doesn't exist (nothing to compile).

### `main()` (L67–L122)
Orchestration function. Early-exit conditions (in order):
1. `SKIP_JDI_COMPILE` env var set (L68–L71)
2. `SKIP_ADAPTER_VENDOR=true` env var set (L73–L76)
3. Source file missing → **hard exit (code 1)** (L78–L81)
4. Compilation not needed (up-to-date) → silent success (L83–L86)
5. `javac` not found → **soft warn, no exit** (L89–L94)
6. `javac` version too old (< 21) → **soft warn, no exit** (L97–L102)

On compilation failure → **hard exit (code 1)** (L119–L121).

Invokes `javac --release 21 <SOURCE_FILE> -d <OUT_DIR>` with `cwd: JAVA_DIR` and `stdio: 'inherit'` (compiler output visible to user).

## Environment Variables
| Variable | Behavior |
|---|---|
| `JAVA_HOME` | If set, used as primary javac search location |
| `SKIP_JDI_COMPILE` | Any truthy value skips compilation entirely |
| `SKIP_ADAPTER_VENDOR` | If `"true"` (case-insensitive, trimmed) skips compilation |

## Architectural Notes
- ESM module using `import.meta.url` + `fileURLToPath` for `__dirname` equivalent (L16–L17)
- Incremental: skips compilation when `.class` is up-to-date (mtime comparison)
- Graceful degradation: missing/old `javac` emits warnings but doesn't block the build — runtime adapter handles the error
- Hard failures only on: missing source file or actual compilation error