# tests\unit\shared\adapter-policy-python.test.ts
@source-hash: 607c09786456e39d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:00Z

## Purpose
Unit test suite for `PythonAdapterPolicy` from the shared package. Validates the Python-specific DAP adapter policy: child session rejection, local variable extraction/filtering, executable path resolution, command queueing behavior, state initialization/transition, adapter matching, initialization ordering (debugpy-specific), attach/pause behavior, and adapter spawn configuration.

## Test Structure

### Top-level describe: `PythonAdapterPolicy` (L4–151)
All tests directly call static methods on `PythonAdapterPolicy` with no instance creation.

### Test Cases

**`rejects child session support` (L5–7)**
- Asserts `PythonAdapterPolicy.buildChildStartArgs('', {})` throws a regex `/does not support child sessions/`.

**`extracts local variables while filtering special entries` (L9–35)**
- Constructs mock `frames`, `scopes`, and `variables` data.
- Calls `PythonAdapterPolicy.extractLocalVariables(frames, scopes, variables)`.
- Expects filtering of: `'special variables'` (exact name) and `'_pydevd_bundle'` (pydevd internal prefix), while retaining `'value'` and `'__name__'`.
- Key contract: entries with name containing `'special variables'` and prefix `_pydevd_bundle` are stripped; standard dunder names like `__name__` are NOT filtered.

**`resolves executable path using precedence rules` (L37–45)**
- Uses `vi.stubEnv('PYTHON_PATH', '/custom/python')` to test env var precedence.
- Precedence: explicit arg > `PYTHON_PATH` env > platform default.
- Platform defaults: `'win32'` → `'python'`; `'linux'` → `'python3'`.

**`does not queue commands and reports initialization state` (L47–60)**
- Verifies `requiresCommandQueueing()` → `false`.
- Verifies `shouldQueueCommand().shouldQueue` → `false`.
- Tests state lifecycle: `createInitialState()` → not initialized; after `updateStateOnEvent('initialized', {}, state)` → `isInitialized` and `isConnected` both `true`.
- After `updateStateOnCommand('configurationDone', {}, state)` → `state.configurationDone === true` (direct field access on state object).

**`matches debugpy adapter commands` (L62–69)**
- `{ command: 'python', args: ['-m', 'debugpy.adapter'] }` → `true`.
- `{ command: 'node', args: ['--inspect'] }` → `false`.

**`requires attach to be sent before the initialized event` (L71–77)**
- `getInitializationBehavior()` → `{ sendAttachBeforeInitialized: true }`.
- Comment documents debugpy issue #145: deadlock if attach is sent after initialized event.

**`pauses the target after attach` (L79–83)**
- `getAttachBehavior?.()` → `{ pauseAfterAttach: true }`.
- Comment explains debugpy does not auto-suspend on attach.

### Nested describe: `getAdapterSpawnConfig` (L85–151)

Shared `basePayload` (L86–91): `{ executablePath: 'python', adapterHost: '127.0.0.1', adapterPort: 40000, logDir: '/logs' }`.

| Test | Input `launchConfig` | Expected output |
|------|---------------------|-----------------|
| connect via `connect` object (L93–100) | `{ request: 'attach', connect: { host, port } }` | `{ mode: 'connect', host: '10.0.0.5', port: 5679, logDir: '/logs' }` |
| connect via top-level host/port (L102–109) | `{ request: 'attach', host, port }` | `{ mode: 'connect', host: '192.168.1.2', port: 5680, logDir: '/logs' }` |
| attach host defaults to 127.0.0.1 (L111–118) | `{ request: 'attach', port: 5681 }` | `{ mode: 'connect', host: '127.0.0.1', port: 5681 }` |
| rejects attach without port (L120–127) | `{ request: 'attach' }` | throws `/debugpy --listen/` |
| spawn for launch (L129–140) | `{ request: 'launch' }` | `{ mode: 'spawn', command: 'python', args: contains ['-m', 'debugpy.adapter'] }` |
| custom adapterCommand for launch (L142–150) | `{ request: 'launch' }` + `adapterCommand: { command: 'py', ... }` | `{ mode: 'spawn', command: 'py' }` |

## Key Dependencies
- `PythonAdapterPolicy`: static-method-only API from `packages/shared/src/interfaces/adapter-policy-python.js`
- `vi.stubEnv`: Vitest environment variable stubbing used in executable path tests (L38, L42)

## Notable Patterns
- All `PythonAdapterPolicy` methods called as static — no instantiation.
- `getAdapterSpawnConfig` and `getAttachBehavior` accessed with optional chaining (`!` / `?.`) suggesting optional interface methods.
- State mutation tested directly via `state.configurationDone` field access (L59).
- `as any` casts for frame/scope/variable mocks (L26–28) to avoid type enforcement in tests.
