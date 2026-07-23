# packages\adapter-python\tests\unit\python-debug-adapter.spec.ts
@source-hash: 946819d2b630b503
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:35Z

## Unit Tests: `PythonDebugAdapter`

Test suite for `PythonDebugAdapter` verifying lifecycle state transitions, environment validation, and error handling. Uses Vitest with mock injection via private-method patching (`(adapter as any).method = vi.fn()`).

### Test Infrastructure

**`createDependencies()` (L6-20):** Factory returning a typed `AdapterDependencies` object with:
- `fileSystem`: empty stub (`{} as any`)
- `environment`: stub returning `undefined` for env vars, `{}` for all env, `'/tmp'` for CWD
- `logger`: `vi.fn()` mocks for `info`, `debug`, `error`

**`setSuccessfulEnvironment(adapter)` (L22-27):** Patches four private methods on an adapter instance to simulate a fully healthy Python environment:
- `resolveExecutablePath` → resolves `'/usr/bin/python3'`
- `checkPythonVersion` → resolves `'3.10.1'`
- `checkDebugpyInstalled` → resolves `true`
- `detectVirtualEnv` → resolves `false`

### Test Cases

| Test | L# | Key Assertion |
|---|---|---|
| Successful initialize → READY | L36-48 | `getState() === READY`, `isReady() === true`, `'initialized'` event emitted |
| Missing debugpy (auto-detected) → still READY | L50-62 | Regression guard for issues #106/#16: missing debugpy during init must NOT block; state still `READY` |
| `validateEnvironment` with old Python + no debugpy (auto-detected) | L64-82 | `valid: false`, error `PYTHON_VERSION_TOO_OLD`, debugpy is a **warning** (not error) when no explicit interpreter provided |
| Configured interpreter: `resolveExecutablePath` receives forwarded path | L85-98 | Spy asserts called with `'/project/.venv/bin/python'`; regression guard for pre-fix bug where `undefined` was passed |
| Configured interpreter: venv debugpy passes even if global missing | L100-112 | `valid: true`, no errors when explicit path's interpreter has debugpy |
| Configured interpreter: missing debugpy is an error | L114-127 | `valid: false`, error `DEBUGPY_NOT_INSTALLED` when explicit interpreter lacks debugpy |
| `dispose()` resets to UNINITIALIZED | L130-139 | `getState() === UNINITIALIZED`, `getCurrentThreadId() === null`, `isReady() === false` |
| `translateErrorMessage` handles ENOENT | L141-145 | Result string contains `'ENOENT'` |

### Critical Behavioral Contracts Tested

1. **debugpy severity depends on context:** `DEBUGPY_NOT_INSTALLED` is a *warning* for auto-detected interpreters (no explicit path given), but an *error* when the user explicitly configures an interpreter path (L76-80 vs L123-126).
2. **issue #106 regression guard:** `validateEnvironment(executablePath)` must forward the path argument to `resolveExecutablePath` — the pre-fix bug called it with `undefined` (L86-88 comment).
3. **State machine:** `initialize()` → `READY`; `dispose()` → `UNINITIALIZED` (L130-139).
4. **`initialized` event:** Emitted by the adapter after successful `initialize()` call (L41-47).

### Dependencies
- `PythonDebugAdapter` from `../../src/python-debug-adapter.js`
- `AdapterState` enum from `@debugmcp/shared` (values used: `READY`, `UNINITIALIZED`)
- `AdapterDependencies` type from `@debugmcp/shared`
