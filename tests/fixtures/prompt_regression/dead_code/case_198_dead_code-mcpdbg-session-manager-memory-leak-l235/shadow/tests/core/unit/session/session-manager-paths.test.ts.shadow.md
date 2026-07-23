# tests\core\unit\session\session-manager-paths.test.ts
@source-hash: b819da0968052cc6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:44Z

## Purpose
Unit tests for `SessionManager` path resolution behavior — specifically verifying that the manager passes paths through unmodified (no normalization, no conversion) when setting breakpoints.

## Test Structure

### Top-level suite: `SessionManager - Path Resolution` (L9–137)
- Uses `vitest` with fake timers (`vi.useFakeTimers({ shouldAdvanceTime: true })`).
- Constructs a fresh `SessionManager` instance per test via `beforeEach` (L14–26) using:
  - `createMockDependencies()` — provides mock infrastructure (proxy manager, etc.)
  - `SessionManagerConfig`: `logDirBase: '/tmp/test-sessions'`, `defaultDapLaunchArgs: { stopOnEntry: true, justMyCode: true }`
- Cleanup in `afterEach` (L28–32): restores real timers, clears mocks, resets `mockProxyManager`.

### Sub-suite: `Windows Path Handling` (L34–92)
| Test | Lines | What it asserts |
|------|-------|-----------------|
| Windows absolute paths with drive letters | L35–55 | `bp.file` equals input path exactly; tests `C:\`, `C:/`, `D:\` variants |
| Backslash separator preservation | L57–73 | `bp.file` contains `src`, `debug`, `file.py` components |
| Pass-through without modification | L75–91 | `bp.file === testPath` for a simple relative path |

### Sub-suite: `Breakpoint Path Resolution` (L94–136)
| Test | Lines | What it asserts |
|------|-------|-----------------|
| Relative paths passed through unmodified | L95–106 | `bp.file === 'src/test.py'` |
| Absolute Unix paths passed through | L108–119 | `bp.file === '/home/user/project/test.py'` |
| Mixed separator preservation | L121–135 | `bp.file` contains `src`, `components`, `test.py` |

## Key Behavioral Contract Being Tested
All tests document the same invariant: **`SessionManager.setBreakpoint()` passes file paths through without any modification or normalization**. Comments throughout (e.g., L50–51, L88–89, L104) explicitly note that path resolution was moved to the server level.

## Common Pattern
All tests follow the same shape:
1. `createSession({ language: DebugLanguage.MOCK, pythonPath: 'python' })` — creates a mock-language session
2. `setBreakpoint(session.id, <path>, <line>)` — sets a breakpoint with a given path
3. Assert `bp.file` equals or contains the expected value

## Dependencies
- `SessionManager`, `SessionManagerConfig` from `src/session/session-manager.js`
- `DebugLanguage` enum from `@debugmcp/shared` — uses `DebugLanguage.MOCK` throughout
- `createMockDependencies` from sibling test utility `session-manager-test-utils.js`