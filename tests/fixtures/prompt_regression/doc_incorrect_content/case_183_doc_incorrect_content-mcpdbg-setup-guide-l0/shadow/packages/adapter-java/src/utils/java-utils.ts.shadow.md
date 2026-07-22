# packages\adapter-java\src\utils\java-utils.ts
@source-hash: ff5673777f6e06f0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:25Z

## Java Utility Functions (`packages/adapter-java/src/utils/java-utils.ts`)

### Purpose
Provides Java runtime detection, version checking, and path resolution utilities for the Java debug adapter. All functions are async-safe and cross-platform aware.

---

### Exported Functions

#### `findJavaExecutable` (L14–40)
Resolves a Java executable path using a three-tier priority chain:
1. **Preferred path** (if provided): validated via `validateJavaExecutable`; throws `Error` if invalid.
2. **`JAVA_HOME` env var**: constructs `$JAVA_HOME/bin/java[.exe]` (`.exe` suffix on `win32`).
3. **`java` in PATH**: attempts bare `java` command.

Throws if no valid Java is found with a message recommending JDK 21+.

**Parameters:** `preferredPath?: string` — optional explicit path to Java binary.

---

#### `validateJavaExecutable` (L45–72)
Spawns `java -version` on the given path and resolves `true` iff:
- The process exits with code `0`, **and**
- At least one byte of output was received on `stdout` or `stderr`.

Uses a `settled` flag to prevent double-resolution across `error` and `exit` events. Resolves `false` on spawn errors or non-zero exit. Never rejects.

**Parameters:** `javaPath: string` — path or command name to test.

---

#### `getJavaVersion` (L77–125)
Spawns `java -version` (or `javaPath -version`) and parses the version string from combined stdout+stderr output.

**Parsing strategy:**
1. Primary regex (L110): `/(?:java|openjdk)\s+version\s+"([^"]+)"/i` — matches canonical `java version "17.0.1"` or `openjdk version "21.0.1"` format.
2. Fallback regex (L115): `/(\d+(?:\.\d+)*)/` — extracts first numeric version sequence.

Returns `null` on error, non-zero exit, or no parseable version. Never rejects.

**Parameters:** `javaPath?: string` — defaults to `'java'`.

---

#### `getJavaSearchPaths` (L130–168)
Returns an ordered `string[]` of candidate Java binary directories. Synchronous.

**Platform-specific additions:**
- All platforms: `$JAVA_HOME/bin` (if set), then `$PATH` entries appended at end.
- `win32` (L138–147): `Program Files\Java`, `Program Files (x86)\Java`, `Eclipse Adoptium`, `Microsoft\jdk`
- `darwin` (L149–154): `/Library/Java/JavaVirtualMachines`, Homebrew OpenJDK paths
- Linux/other (L155–162): `/usr/lib/jvm`, `/usr/local/lib/jvm`, `/usr/bin`, `/usr/local/bin`

---

### Key Patterns
- **Settled flag pattern** (L47, L81): Guards `Promise` resolution against duplicate event firing from `child_process` — used in all three async functions.
- **Optional `.?` on stdio streams** (L54–55, L89–93): Guards against `null` streams despite `stdio: 'pipe'` configuration — defensive but harmless.
- **`java -version` writes to stderr** by JVM convention; both streams are captured to handle JVM variants that differ.

---

### Dependencies
- `child_process.spawn` — spawns Java subprocess for validation/version queries.
- `path` — cross-platform path construction (`path.join`, `path.delimiter`).
- `process.env.JAVA_HOME`, `process.env.PATH`, `process.platform` — runtime environment detection.