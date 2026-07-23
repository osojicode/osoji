# packages\adapter-python\tests\unit\python-adapter-factory.test.ts
@source-hash: db0373084872da4f
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:47Z

## Purpose
Unit tests for `PythonAdapterFactory`, covering adapter creation, metadata retrieval, and environment validation logic (Python version checks, debugpy detection).

## Test Structure

### Mocks (L11–26)
- **`python-utils.js`** fully mocked: `findPythonExecutable` and `getPythonVersion` become `vi.fn()` instances.
- **`child_process`** partially mocked: real module spread, then `spawn` overridden with `vi.fn()`.
- Typed mock references: `findPythonExecutableMock` (L24), `getPythonVersionMock` (L25), `spawnMock` (L26).

### Helper: `createDependencies` (L28–42)
Returns a minimal `AdapterDependencies`-compatible object with stub `fileSystem`, `environment` (always returns `undefined`/`{}`/`cwd()`), and silent `logger`. Used as the argument to `factory.createAdapter()`.

### Helper: `simulateSpawn` (L44–65)
Sets up `spawnMock` to return a fake child process (`EventEmitter` with `.stdout` child `EventEmitter`) that asynchronously (via `queueMicrotask`) emits:
- `'error'` on `child` if `emitError: true`
- optional `'data'` on `stdout` with the `output` buffer
- `'exit'` on `child` with `exitCode`

This mirrors how `PythonAdapterFactory.validate()` detects debugpy via spawned process.

## Test Cases (L67–196)

| Test | Key assertions |
|------|---------------|
| Creates `PythonDebugAdapter` (L75–80) | `factory.createAdapter(deps)` returns `instanceof PythonDebugAdapter` |
| Metadata (L82–95) | `language: DebugLanguage.PYTHON`, `displayName: 'Python'`, `version: '2.0.0'`, `author`, `documentationUrl`, `fileExtensions: ['.py', '.pyw']` |
| Validate — all available (L97–113) | `valid: true`, empty errors/warnings, `details.pythonPath`, `details.pythonVersion`, `details.platform` |
| Validate — Python not found (L115–123) | `findPythonExecutable` rejects → `valid: false`, error includes message |
| Validate — Python < 3.7 (L125–135) | `getPythonVersion` returns `'3.6.9'` → `valid: false`, specific error message |
| Validate — version undetermined (L137–148) | `getPythonVersion` returns `undefined` → `valid: true`, warning contains `'Could not determine Python version'` |
| Validate — debugpy exit code 1 (L150–161) | spawn exits with code 1 → `valid: true`, warning includes `'debugpy'` |
| Validate — debugpy spawn error (L163–174) | spawn emits `'error'` event → `valid: true`, warning includes `'debugpy'` |
| Virtualenv scenario / issue #16 (L176–196) | Python valid (3.11.0), debugpy missing (exit 1) → `valid: true`, no errors, debugpy warning, details populated |

## Key Design Observations
- **debugpy absence is non-blocking**: Both spawn-error and non-zero-exit cases yield `valid: true` with warnings only — validated by multiple tests and explicitly documented in the virtualenv scenario (issue #16 regression test, L176–196).
- **Python version floor**: 3.7 is the minimum; anything below causes `valid: false` with a specific message.
- **`queueMicrotask` in `simulateSpawn`**: Ensures spawn event emissions happen after the current synchronous call stack, correctly simulating async child process behavior.

## Dependencies
- `PythonAdapterFactory` from `../../src/python-adapter-factory.js`
- `PythonDebugAdapter` from `../../src/python-debug-adapter.js`
- `findPythonExecutable`, `getPythonVersion` from `../../src/utils/python-utils.js`
- `AdapterDependencies`, `DebugLanguage` from `@debugmcp/shared`
- `vitest` for test runner and mocking; `events.EventEmitter` for child process simulation