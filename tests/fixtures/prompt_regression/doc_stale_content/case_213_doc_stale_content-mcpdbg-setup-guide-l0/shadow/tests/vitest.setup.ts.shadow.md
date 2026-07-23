# tests\vitest.setup.ts
@source-hash: 5330f16d3d14fa4e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:02Z

## Vitest Global Setup File (`tests/vitest.setup.ts`)

Runs before every test file in the suite. Installs process-level diagnostics, port-manager lifecycle hooks, mock/env cleanup, and a process-listener leak guard. Registers no test assertions itself — purely infrastructure.

---

### Key Responsibilities

1. **Unhandled error surfacing (L22–37)**
   - Registers `process.on('unhandledRejection', ...)` and `process.on('uncaughtException', ...)` at module load time.
   - Uses `currentTestPath()` (L13–19) to annotate which test file triggered the error.
   - Both handlers are added to the baseline snapshot (they are intentionally exempt from the leak guard).

2. **ESM `__dirname` shim (L51–58)**
   - Sets `globalThis.__dirname` from `import.meta.url` with a Windows-path fixup regex (`/^\/([A-Za-z]:)\//` → `'$1/'`).
   - Falls back to `process.cwd()` if `import.meta.url` is unavailable.
   - Secondary Windows normalisation: replaces all `/` with `\\` on `win32` (L56–58).

3. **Global `testPortManager` (L61)**
   - Exposes `portManager` as `globalThis.testPortManager` so individual test files can allocate ports without importing the helper directly.

4. **`beforeAll` hook (L64–67)**
   - Calls `portManager.reset()` before each test file to start with a clean port-allocation state.

5. **Process-listener leak guard (L69–128) — issue #159**
   - `GUARDED_PROCESS_EVENTS` (L79–88): `const` tuple of 8 event names guarded (`uncaughtException`, `unhandledRejection`, `SIGTERM`, `SIGINT`, `message`, `disconnect`, `error`, `exit`). `'warning'` is **intentionally excluded** because `src/index.ts` installs a module-level noop listener on that event.
   - `processListenerBaseline` (L94–99): `Map<string, Set<ProcessListener>>` snapshot of all raw listeners installed by vitest/tinypool *before* any test runs. Captured at module-load time.
   - `afterEach` hook (L104–128): Iterates guarded events; removes any listener not in the baseline; accumulates leaked event names. Logs a diagnostic message with test name and file. If `process.env.LEAK_GUARD_STRICT` is set, throws to fail the test hard.
   - **Hook ordering**: registered *before* the mock-reset `afterEach`; vitest's default `sequence.hooks = 'stack'` (LIFO) makes it run *last*, ensuring mock state is torn down before the leak check fires.

6. **Mock/env cleanup `afterEach` (L131–140)**
   - `vi.resetAllMocks()` + `vi.restoreAllMocks()` — resets all spies/mocks.
   - `vi.unstubAllEnvs()` — cleans up `vi.stubEnv()` calls centrally so env vars cannot leak between tests/files.

7. **`afterAll` hook (L143–148)**
   - Calls `portManager.reset()` after all tests complete.
   - Comment notes that `session-helpers.ts` was removed as dead code (no tests imported it).

---

### Helper

| Symbol | Lines | Description |
|---|---|---|
| `currentTestPath()` | L13–19 | Returns `expect.getState().testPath` or `''`; wrapped in try/catch for safety outside test context. |

### Type & Constant Definitions

| Symbol | Lines | Description |
|---|---|---|
| `GUARDED_PROCESS_EVENTS` | L79–88 | `readonly` tuple of process event names subject to leak detection. |
| `ProcessListener` | L90 | `type` alias `(...args: unknown[]) => void` for raw process listeners. |
| `processListenerBaseline` | L94–99 | Module-level `Map` snapshot of pre-test process listeners. |

---

### Environment Variable Contract

| Variable | Usage |
|---|---|
| `CONSOLE_OUTPUT_SILENCED` | **Deleted** from `process.env` at module load (L40) to ensure console is active unless tests re-set it. |
| `LEAK_GUARD_STRICT` | If truthy, the leak guard `afterEach` throws instead of just logging (L124–126). |

---

### Global Augmentations

Declared on `global` (L43–48):
- `__dirname: string`
- `testPortManager: typeof portManager`

---

### Dependencies

- `vitest` — `vi`, `beforeAll`, `afterEach`, `afterAll`, `expect`
- `./test-utils/helpers/port-manager.js` — `portManager` singleton