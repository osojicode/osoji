# tests\unit\shared\adapter-policy-go.test.ts
@source-hash: 144686429e4cc4f2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:59Z

## Purpose
Unit test suite for `GoAdapterPolicy` — the Go (Delve DAP) adapter policy implementation. Covers identity, child session handling, variable extraction, scope/configuration, executable resolution, session readiness, command queueing, state management, adapter matching, initialization behavior, DAP client behavior, stack frame filtering, spawn config, and executable validation.

## Test File Structure
Single `describe('GoAdapterPolicy')` block (L22–492) with nested `describe('validateExecutable')` (L456–491). Tests are organized into clearly labeled sections via inline comments.

## Key Test Groups

### Identity (L25–35)
- `name` is `'go'`
- `supportsReverseStartDebugging` is `false`
- `childSessionStrategy` is `'none'`

### Child Sessions (L39–53)
- `buildChildStartArgs` throws `/does not support child sessions/`
- `shouldDeferParentConfigDone()` returns `false`
- `isChildReadyEvent` returns `true` only for `event: 'initialized'`

### Local Variable Extraction (L57–175)
- `extractLocalVariables` uses scope names `'Locals'` or `'Local'` (L57–93)
- Filters out underscore-prefixed names except bare `'_'` (L95–117)
- `includeSpecial: true` bypasses the filter (L119–136)
- Returns `[]` for: no frames, no scopes, empty scopes array, wrong scope name, missing variables (L138–175)

### Scope & Configuration (L179–192)
- `getLocalScopeName()` returns `['Locals', 'Arguments']`
- `getDapAdapterConfiguration()` returns `{ type: 'dlv-dap' }`
- `getDebuggerConfiguration()`: `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true`

### Executable Resolution (L196–208)
- Uses provided path directly
- Falls back to `DLV_PATH` env var
- Defaults to `'dlv'`

### Session Readiness (L212–216)
- `isSessionReady` returns `true` only for `SessionState.PAUSED`

### Command Queueing (L220–228)
- `requiresCommandQueueing()` returns `false`
- `shouldQueueCommand()` returns `{ shouldQueue: false, shouldDefer: false }`

### State Management (L232–274)
- `createInitialState()` returns `{ initialized: false, configurationDone: false }`
- `updateStateOnCommand('configurationDone', ...)` sets `state.configurationDone = true`
- `updateStateOnEvent('initialized', ...)` sets `state.initialized = true`
- `isInitialized` and `isConnected` both reflect `state.initialized`

### Adapter Matching (L278–306)
- Matches command `'dlv'`, path ending in `/dlv`, args containing `'dlv dap'` or `'delve'`
- Does not match unrelated commands (e.g., `'python'`)

### Initialization Behavior (L310–315)
- `deferConfigDone: false`, `defaultStopOnEntry: false`, `sendLaunchBeforeConfig: true`

### DAP Client Behavior (L319–348)
- `childInitTimeout: 5000`, all boolean flags `false`
- `handleReverseRequest` handles `'runInTerminal'` (returns `handled: true`, calls `sendResponse`)
- Returns `handled: false` for unknown reverse requests

### Stack Frame Filtering (L352–402)
- `filterStackFrames` removes frames whose `file` path contains `/runtime/` or `/testing/` (Go stdlib paths)
- `includeInternals: true` bypasses filter
- Empty file path frames are kept (not matched by runtime/testing patterns)
- `isInternalFrame` returns `true` for runtime/testing frames, `false` for user frames

### Adapter Spawn Config (L406–452)
- When `adapterCommand` provided: uses its `command`, `args`, `env`; sets `host` and `port`
- Default: builds `dlv dap --listen host:port --log --log-dest /logDir` args
- Defaults to `'dlv'` when no `executablePath` specified

### validateExecutable (L456–491)
- Uses `mockSpawnChild` helper (L12–20) to script `child.stdout` data and exit/error events
- `child_process` is fully mocked via `vi.mock` (L9) — hermetic, no real process spawned
- `true` only when exit code 0 AND stdout produced data
- `false` on spawn error, non-zero exit, or zero exit with no output
- Asserts spawn called with `['version']` argument

## Mock Infrastructure
- `vi.mock('child_process', ...)` at L9 replaces `spawn` globally
- `mockSpawnChild(script)` (L12–20): Creates an `EventEmitter` with a `.stdout` `EventEmitter`, delays script execution via `setImmediate` so listeners attach first, returns it as the spawn return value

## Dependencies
- `GoAdapterPolicy` from `../../../packages/shared/src/interfaces/adapter-policy-go.js`
- `SessionState` from `@debugmcp/shared`
- `spawn` from `child_process` (mocked)
- `EventEmitter` from `events`
