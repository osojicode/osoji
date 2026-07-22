# packages\shared\src\interfaces\adapter-policy-python.ts
@source-hash: d363356eb0272a02
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:55Z

## PythonAdapterPolicy (L12-344)

A concrete implementation of the `AdapterPolicy` interface for Python's **debugpy** debug adapter. This is a singleton object (not a class) that encodes all debugpy-specific behaviors, variable handling, spawn configuration, and state management for Python debug sessions.

---

### Primary Responsibility
Provides all Python/debugpy-specific logic for the debug adapter framework: executable resolution, session initialization sequencing, variable filtering, attach/spawn configuration, and DAP client behavior. Consumed by the adapter framework to drive Python debug sessions.

---

### Key Properties & Methods

| Name | Line | Description |
|---|---|---|
| `name` | 13 | Discriminant: `'python'` |
| `supportsReverseStartDebugging` | 14 | `false` — debugpy never acts as a reverse-start initiator |
| `childSessionStrategy` | 15 | `'none'` — Python has no child session concept |
| `shouldDeferParentConfigDone` | 16 | Always returns `false` |
| `buildChildStartArgs` | 17–19 | Throws unconditionally (child sessions unsupported) |
| `isChildReadyEvent` | 20–22 | Returns `true` if `evt.event === 'initialized'` |
| `extractLocalVariables` | 27–85 | Extracts local variables from top stack frame; finds `'Locals'`/`'Local'` scope; filters out `special variables`, `function variables`, most dunders (keeps `__name__`, `__file__`, `__doc__`), and `_pydev*`/`_` internal names unless `includeSpecial=true` |
| `getLocalScopeName` | 90–92 | Returns `['Locals', 'Local']` |
| `getDapAdapterConfiguration` | 94–98 | Returns `{ type: 'debugpy' }` |
| `resolveExecutablePath` | 100–114 | Priority: `providedPath` → `PYTHON_PATH` env var → `'python'` (win32) / `'python3'` (other) |
| `getDebuggerConfiguration` | 116–123 | Returns `{ requiresStrictHandshake: false, skipConfigurationDone: false, supportsVariableType: true }` |
| `isSessionReady` | 125 | `state === SessionState.PAUSED` |
| `validateExecutable` | 131–160 | Spawns `pythonCmd -c 'import sys; sys.exit(0)'`; detects Windows Store aliases via exit code 9009 or stderr content; resolves `false` for store aliases or non-zero exit, `true` for exit 0 |
| `requiresCommandQueueing` | 165 | Always `false` |
| `shouldQueueCommand` | 170–177 | Returns `{ shouldQueue: false, shouldDefer: false, reason: '...' }` |
| `createInitialState` | 182–187 | Returns `{ initialized: false, configurationDone: false }` |
| `updateStateOnCommand` | 192–196 | Sets `state.configurationDone = true` when `command === 'configurationDone'` |
| `updateStateOnEvent` | 201–205 | Sets `state.initialized = true` when `event === 'initialized'` |
| `isInitialized` | 210–212 | Returns `state.initialized` |
| `isConnected` | 217–219 | Returns `state.initialized` (connected once initialized) |
| `matchesAdapter` | 225–233 | Returns `true` if command or args (lowercased) include `'debugpy'` or command includes `'python'` |
| `getInitializationBehavior` | 240–244 | Returns `{ sendAttachBeforeInitialized: true }` — critical: debugpy only emits `'initialized'` AFTER receiving launch/attach (issue #145) |
| `getAttachBehavior` | 249 | Returns `{ pauseAfterAttach: true }` — debugpy doesn't auto-pause on attach |
| `getDapClientBehavior` | 254–281 | Returns `DapClientBehavior` with: `handleReverseRequest` that acknowledges `runInTerminal` only; `mirrorBreakpointsToChild: false`; `deferParentConfigDone: false`; `pauseAfterChildAttach: false`; `childInitTimeout: 5000`; `suppressPostAttachConfigDone: false` |
| `getAdapterSpawnConfig` | 286–344 | Three branches: (1) **attach mode** → validates port, returns `{ mode: 'connect', host, port, logDir }`; (2) **custom adapterCommand** → returns `{ mode: 'spawn', ... }` with provided args; (3) **default** → spawns `python3 -m debugpy.adapter --host ... --port ... --log-dir ...` |

---

### Architecture Notes

- **No child sessions**: `childSessionStrategy: 'none'`, `buildChildStartArgs` throws, `getDapClientBehavior` sets all child-related flags to `false`/`undefined`.
- **Initialization sequencing quirk**: debugpy requires launch/attach to be sent *before* it emits `'initialized'` (opposite of many adapters). This is handled by `getInitializationBehavior: { sendAttachBeforeInitialized: true }` (L240–244), documented as issue #145 fix.
- **Attach requires running debugpy**: In attach mode, `getAdapterSpawnConfig` returns `mode: 'connect'` (no spawning); the user must have started `python -m debugpy --listen host:port` themselves.
- **Windows Store alias detection**: `validateExecutable` (L131–160) checks for exit code 9009 and specific stderr substrings to distinguish real Python from the Windows Store stub.
- **Platform-aware defaults**: Both `resolveExecutablePath` and `getAdapterSpawnConfig` fallback to `'python'` on win32 and `'python3'` elsewhere.

---

### Dependencies
- `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` — from `./adapter-policy.js`
- `SessionState` — from `@debugmcp/shared` (used in `isSessionReady`)
- `StackFrame`, `Variable` — from `../models/index.js`
- `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult` — from `./dap-client-behavior.js`
- `DebugProtocol` — from `@vscode/debugprotocol`
- `child_process.spawn` — dynamically imported in `validateExecutable` to avoid browser-environment issues
