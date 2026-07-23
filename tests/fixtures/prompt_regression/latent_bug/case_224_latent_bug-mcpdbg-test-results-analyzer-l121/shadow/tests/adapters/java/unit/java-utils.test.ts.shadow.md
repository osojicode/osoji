# tests\adapters\java\unit\java-utils.test.ts
@source-hash: 5c9cc59a71ab3688
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:48Z

## Purpose
Unit tests for Java utility functions (`findJavaExecutable`, `getJavaVersion`, `getJavaSearchPaths`) exported from `@debugmcp/adapter-java`. Tests use `vitest` with `child_process.spawn` mocked via `vi.mock`.

## Test Structure

### Setup (L22–29)
- `beforeEach`: `vi.clearAllMocks()` resets mock state between tests.
- `afterEach`: `vi.clearAllMocks()` + `vi.unstubAllGlobals()` resets env stubs.
- `mockSpawn` (L19): typed reference to the mocked `spawn` via `vi.mocked(spawn)`.

### Mock Pattern
All `spawn` mocks create an `EventEmitter`-based fake process with `.stdout` and `.stderr` child `EventEmitter`s (L34–41). Events are emitted asynchronously via `process.nextTick`. Java version output always comes from `stderr` (not stdout), reflecting real `java -version` behavior.

---

## `findJavaExecutable` Tests (L31–116)

| Test | Behavior |
|---|---|
| L32–46 | Preferred path `/custom/java` validates → returns it |
| L48–59 | Preferred path emits `error` event → rejects with `'not valid'` |
| L61–79 | `JAVA_HOME` set → result contains `test/jdk` (path-sep normalized) |
| L81–101 | `JAVA_HOME` unset; only `cmd === 'java'` succeeds → returns `'java'` |
| L103–115 | `JAVA_HOME` unset; all spawn fail → rejects with `'Java not found'` |

Key detail (L78, L191): Path comparison uses `.split(path.sep).join('/')` to normalize cross-platform separators.

---

## `getJavaVersion` Tests (L118–176)

| Test | Behavior |
|---|---|
| L119–133 | Modern version string `"17.0.1"` in stderr → returns `'17.0.1'` |
| L135–149 | Legacy format `"1.8.0_301"` in stderr → returns `'1.8.0_301'` |
| L151–162 | Spawn error event → returns `null` |
| L164–175 | Non-zero exit code (1) → returns `null` |

---

## `getJavaSearchPaths` Tests (L178–205)

| Test | Behavior |
|---|---|
| L179–183 | Returns non-empty array |
| L185–192 | `JAVA_HOME` set → first path contains `custom/jdk/bin` |
| L194–204 | PATH entries from `process.env.PATH` are represented in result (conditionally tested) |

The PATH separator is determined at runtime: `;` on win32, `:` otherwise (L199).

---

## Key Dependencies
- **`@debugmcp/adapter-java`**: Source under test; exports `findJavaExecutable`, `getJavaVersion`, `getJavaSearchPaths` (L5–9).
- **`child_process`**: Fully mocked at module level (L11–17); only `spawn` is replaced with a `vi.fn()`.
- **`vitest`**: Test framework with `vi.stubEnv` for environment variable injection.
- **`EventEmitter`**: Used to construct fake child processes with `stdout`/`stderr` streams.

## Notable Patterns
- `child_process` mock preserves non-`spawn` exports via `importOriginal` spread (L12–16).
- `vi.stubEnv('JAVA_HOME', undefined)` is used to clear the env var (L82, L104) — note `undefined` rather than deleting the key.
- Tests rely on `process.nextTick` for asynchronous event emission, simulating real process lifecycle without actual subprocesses.
