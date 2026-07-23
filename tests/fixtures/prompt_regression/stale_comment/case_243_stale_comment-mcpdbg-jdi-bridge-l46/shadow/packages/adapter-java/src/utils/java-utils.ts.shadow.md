# packages\adapter-java\src\utils\java-utils.ts
@source-hash: ff5673777f6e06f0
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:48Z

## Java Utility Functions (`packages/adapter-java/src/utils/java-utils.ts`)

### Purpose
Provides Java runtime detection, version checking, and path resolution utilities for the Java debug adapter. All functions are pure async I/O helpers with no shared state.

---

### Exported Functions

#### `findJavaExecutable` (L14–40)
Resolves the Java executable path with priority order:
1. `preferredPath` (if provided and valid) — throws if invalid
2. `$JAVA_HOME/bin/java[.exe]` (platform-aware extension at L25)
3. `'java'` from `PATH`

Throws descriptive `Error` if no valid Java is found (L37–39, recommends JDK 21+).

#### `validateJavaExecutable` (L45–72)
Spawns `java -version` and returns `true` only if:
- Process exits with code `0` AND
- At least one byte of output was received on stdout or stderr (`hasOutput`)

Uses a `settled` guard flag (L47) to prevent double-resolution of the Promise in race between `error` and `exit` events.

#### `getJavaVersion` (L77–125)
Spawns `java -version` (or a provided `javaPath`) and parses the version string from stderr/stdout output.

Two-pass parsing strategy:
1. Primary regex (L110): matches `java version "X.Y.Z"` or `openjdk version "X.Y.Z"` (case-insensitive)
2. Fallback regex (L115): matches first numeric sequence `\d+(\.\d+)*`

Returns `null` on error, non-zero exit, or unparseable output.

#### `getJavaSearchPaths` (L130–168)
Returns ordered list of filesystem paths where Java installations are commonly found:
1. `$JAVA_HOME/bin` (if set)
2. Platform-specific common locations:
   - **Windows**: `%ProgramFiles%/Java`, `%ProgramFiles(x86)%/Java`, Eclipse Adoptium, Microsoft JDK (L140–147)
   - **macOS**: `/Library/Java/JavaVirtualMachines`, Homebrew OpenJDK paths (L150–154)
   - **Linux**: `/usr/lib/jvm`, `/usr/local/lib/jvm`, `/usr/bin`, `/usr/local/bin` (L156–161)
3. All entries from `$PATH` (split by `path.delimiter`)

---

### Key Patterns

- **`settled` guard pattern** (L47, L81): Both `validateJavaExecutable` and `getJavaVersion` use a boolean guard to safely handle the race between `child.on('error')` and `child.on('exit')` events, preventing double-resolution.
- **`java -version` outputs to stderr** by convention — both stdout and stderr are captured (L54–55, L89–94).
- Platform branching uses `process.platform === 'win32'` / `'darwin'` checks; Linux/other is the `else` branch.
- Windows `.exe` extension handled at L25 inside `findJavaExecutable` only; `getJavaSearchPaths` does not append extensions.

---

### Dependencies
- `child_process.spawn` — used to invoke `java -version` subprocess
- `path` (Node stdlib) — used for `path.join`, `path.delimiter`
- `process.env` — reads `JAVA_HOME`, `PATH`, `ProgramFiles`, `ProgramFiles(x86)`
- `process.platform` — drives Windows/macOS/Linux branching
