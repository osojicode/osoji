# tests\unit\test-utils\mock-factories.ts
@source-hash: af90b2f631182194
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:01Z

## Purpose
Factory functions for creating fully-configured mock objects used in unit tests. Each factory returns a vitest mock object with pre-configured return values and spy functions, ensuring consistent and reusable test fixtures across the test suite.

## Key Exports

### `createMockChildProcess` (L15–38)
Returns a `ChildProcess & EventEmitter` hybrid. Constructs via `new EventEmitter()` cast, then manually assigns all `ChildProcess` properties:
- Streams: `stdin`, `stdout`, `stderr` (each `new EventEmitter() as any`)
- Primitives: `pid=12345`, `connected=true`, `exitCode=null`, `signalCode=null`, `killed=false`, `spawnargs=[]`, `spawnfile=''`
- Methods (vi.fn): `send` (→ `true`), `kill` (→ `true`), `ref`/`unref` (→ `this`), `disconnect`

### `createMockProxyProcess` (L43–54)
Returns `EventEmitter` extended with `{ send, sendCommand, kill, pid:12345, stderr, stdout }` via `Object.assign`. Less typed than `createMockChildProcess`; intended for proxy-layer tests.

### `createMockSessionManager` (L59–105)
Returns a plain object with all session lifecycle and debug operations as `vi.fn()` mocks:
- `createSession` → `{ sessionId:'session-123', success:true }`
- `getSessionById` → `{ id:'session-123', language:'python', state:{ lifecycleState:'READY' } }`
- `closeSession`, `closeAllSessions` → `{ success:true }`
- `setBreakpoint` → `{ success:true, breakpointId:'bp-1' }`
- `startDebugging`, `stepOver`, `stepInto`, `stepOut`, `continue` → `{ success:true }`
- `getVariables` → `{ success:true, variables:[] }`
- `getStackTrace` → `{ success:true, frames:[] }`
- `getScopes` → `{ success:true, scopes:[] }`
- `evaluateExpression` → `{ success:true, result:'', type:'string' }`
- `getAdapterRegistry` → `null`, `adapterRegistry: null`

### `createMockAdapterRegistry` (L110–122)
Returns mock adapter registry: `getSupportedLanguages`/`listLanguages`/`listAvailableAdapters` → `['python','mock']`; `isLanguageSupported` → `true`; `create`/`getAdapter` → `null`; `hasAdapter` → `false`; `listAdapters` → `[]`.

### `createMockWhichFinder` (L127–131)
Returns `{ find: vi.fn().mockResolvedValue('/usr/bin/python3') }`. Simulates successful Python binary lookup.

### `createMockLogger` (L136–143)
Returns `{ debug, info, warn, error }` all as `vi.fn()`. Matches standard logger interface.

### `createMockFileSystem` (L148–162)
Returns fs-extra-style mock: `ensureDir`/`writeFile` → `undefined`; `pathExists` → `true`; `readFile` → `''`; `stat` → `{ isFile:()=>true, isDirectory:()=>false, size:0, mtime:new Date() }`.

### `createMockNetworkManager` (L167–171)
Returns `{ findFreePort: vi.fn().mockResolvedValue(12345) }`.

### `createMockEnvironment` (L176–181)
Returns plain object `{ isContainer: false, containerWorkspaceRoot: undefined }`. Not a vi.fn()-based mock.

### `createPythonValidationProcess` (L186–195)
Composes `createMockChildProcess()`, then schedules `mockProcess.emit('exit', 0)` on `process.nextTick`. Simulates a successful Python validation subprocess.

### `createFailedPythonValidationProcess` (L200–208)
Same as above but emits `exit` with code `1` on `process.nextTick`. Simulates Python validation failure.

## Architectural Patterns
- All factories use **vitest `vi.fn()`** for spyable methods, enabling `expect(...).toHaveBeenCalledWith(...)` assertions in tests.
- **EventEmitter composition** is used for process mocks, enabling `emit`-based event simulation without real process spawning.
- `createPythonValidationProcess` and `createFailedPythonValidationProcess` use `process.nextTick` to defer event emission, ensuring tests can attach listeners before the event fires.
- Consistent `pid: 12345` and `sessionId: 'session-123'` across factories — tests expecting specific values should match these defaults.
- `createMockEnvironment` returns a plain literal (no vi.fn), so its properties cannot be spied on directly.

## Dependencies
- `vitest`: `vi` for mock functions
- `events`: `EventEmitter` for process mock base
- `child_process`: `ChildProcess` type only (no runtime dependency)
