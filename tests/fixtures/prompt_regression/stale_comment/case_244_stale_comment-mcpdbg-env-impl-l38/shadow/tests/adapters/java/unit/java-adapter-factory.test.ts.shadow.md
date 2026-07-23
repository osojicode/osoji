# tests\adapters\java\unit\java-adapter-factory.test.ts
@source-hash: 2820cc513484748a
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:42Z

## Unit Tests: JavaAdapterFactory

Tests for `JavaAdapterFactory` and `JavaDebugAdapter` from `@debugmcp/adapter-java`, covering factory creation, metadata retrieval, and environment validation logic.

### Test Structure

**Top-level suite:** `JavaAdapterFactory` (L49–208)

Uses `vitest` with `vi.mock('child_process')` (L8–14) to intercept `spawn` calls, enabling simulation of Java installation scenarios without requiring a real JRE.

### Key Helpers

- **`createMockDependencies()` (L18–47):** Produces a stub `AdapterDependencies` object with no-op filesystem methods, spy logger functions, and environment accessors delegating to `process.env`. Returned fresh per test via inline call.

- **`mockSpawn` (L16):** `vi.mocked(spawn)` — typed reference to the mocked `child_process.spawn`. Each validation test overrides it with a custom `mockImplementation` that returns an `EventEmitter`-based pseudo-process with `.stdout`, `.stderr`, and asynchronous emission via `process.nextTick`.

### Test Groups

#### `createAdapter` (L62–72)
- Verifies `factory.createAdapter(deps)` returns a `JavaDebugAdapter` instance (L65).
- Verifies `adapter.language === DebugLanguage.JAVA` (L70).

#### `getMetadata` (L74–89)
- Checks metadata fields: `language === DebugLanguage.JAVA`, `displayName === 'Java'`, `version === '0.2.0'`, `description` contains `'JDI'`, `fileExtensions` contains `'.java'`.
- Checks `documentationUrl` contains `'github.com'`.

#### `validate` (L91–208)
All tests mock `spawn` to simulate different Java environment conditions:

| Test | Spawn behavior | Expected outcome |
|---|---|---|
| Java available (L92–112) | Emits stderr `openjdk version "17.0.1"`, exit 0 | `valid: true`, no errors, `details.javaPath` defined |
| Java not found (L114–130) | Emits `error` (`spawn ENOENT`); `PATH=''`, `JAVA_HOME=undefined` stubbed | `valid: false`, errors present |
| JDI bridge not compiled (L132–149) | Java 17 exit 0 | Checks presence of `'JDI bridge'` in warnings (environment-dependent, only verifies boolean type) |
| Platform info in details (L151–168) | Java 17 exit 0 | `details.platform === process.platform`, `details.arch === process.arch`, `details.timestamp` defined |
| Java < 21 warning (L170–188) | Java 17 exit 0 | `valid: true`, warning `'Java 21+ recommended'`, `details.javaVersion === '17.0.1'` |
| Java ≥ 21 no warning (L190–207) | Java 21 exit 0 | `valid: true`, no `'Java 21+ recommended'` warning |

### Mock Process Pattern (L93–104, L115–121, L133–142, etc.)
Each spawn mock returns:
```
EventEmitter + { stdout: EventEmitter, stderr: EventEmitter }
```
Async events fired via `process.nextTick` to simulate non-blocking I/O. The factory's `validate()` reads Java version from **stderr** (as is standard for `java -version` output).

### Dependencies
- `@debugmcp/shared`: `AdapterDependencies` (type), `DebugLanguage` (enum)
- `@debugmcp/adapter-java`: `JavaAdapterFactory`, `JavaDebugAdapter`
- `child_process`: `spawn` — fully mocked via `vi.mock`
- `events`: `EventEmitter` — used in mock process construction
- `vitest`: test runner, spy/mock utilities

### Key Constraints
- Factory is re-instantiated before each test (`beforeEach`, L52–55) with `vi.clearAllMocks()`.
- `vi.unstubAllGlobals()` called in `afterEach` (L59) to clean up `PATH`/`JAVA_HOME` environment stubs.
- Tests do NOT call `factory.createAdapter()` in validate tests — `validate()` is called directly on the factory without dependencies.
- Version `'0.2.0'` (L80) is asserted as exact match — brittle to version bumps.
