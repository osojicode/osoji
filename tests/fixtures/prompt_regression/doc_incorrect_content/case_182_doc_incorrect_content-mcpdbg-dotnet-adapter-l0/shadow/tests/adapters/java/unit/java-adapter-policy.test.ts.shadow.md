# tests\adapters\java\unit\java-adapter-policy.test.ts
@source-hash: cc33485c9a9b84d0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:24Z

## Purpose
Unit test suite for `JavaAdapterPolicy` from `@debugmcp/shared`, verifying all behavioral contracts of the Java DAP adapter policy object including adapter matching, state management, stack frame filtering, variable extraction, spawn config, and DAP client behavior.

## Test Structure
All tests are in a single top-level `describe('JavaAdapterPolicy')` block (L5–414), organized into sub-suites by method/feature area. Uses vitest (`describe`, `it`, `expect`, `vi`).

## Key Test Groups

### Basic Properties (L6–18)
- `name` === `'java'`
- `supportsReverseStartDebugging` === `false`
- `childSessionStrategy` === `'none'`

### `matchesAdapter` (L20–55)
- Matches if args contain `JdiDapServer`, `jdi-bridge`, or `java-debug`
- Does NOT match `dlv` or `debugpy` commands

### `getLocalScopeName` (L57–62)
- Returns array containing `'Locals'`

### `getDapAdapterConfiguration` (L64–69)
- Returns config with `type === 'java'`

### `resolveExecutablePath` (L71–92)
- Returns provided path as-is when supplied (L73–75)
- Builds path from `JAVA_HOME` env var when set (L77–84) — uses `vi.stubEnv`
- Defaults to `'java'` string when `JAVA_HOME` unset (L86–91)

### State Management (L94–121)
- `createInitialState()` returns `{ initialized: false, configurationDone: false }`
- `updateStateOnEvent('initialized', {}, state)` sets `state.initialized = true`
- `isInitialized(state)` reflects `initialized` flag
- `updateStateOnCommand('configurationDone', undefined, state)` sets `state.configurationDone = true`
- `isConnected(state)` returns `true` only after initialized event

### `isSessionReady` (L123–135)
- `true` for `SessionState.PAUSED`
- `false` for `SessionState.RUNNING` and `SessionState.CREATED`

### Command Queueing (L137–147)
- `requiresCommandQueueing()` === `false`
- `shouldQueueCommand()` returns `{ shouldQueue: false, shouldDefer: false }`

### `filterStackFrames` (L149–171, L374–396)
- Filters out frames where name starts with `java.*`, `sun.*` etc. when `includeInternals=false`
- Passes all frames when `includeInternals=true`
- Also filters by file path: removes frames with `/jdk/` or `/rt.jar/` in path (L374–396)

### `isInternalFrame` (L173–189)
- `java.*`, `javax.*`, `sun.*` prefixed frame names → internal (`true`)
- User frames (e.g. `com.example.*`) → not internal (`false`)

### `getInitializationBehavior` (L191–198)
- Returns `{ sendLaunchBeforeConfig: true }` with `deferConfigDone` and `defaultStopOnEntry` both undefined
- Comment documents JDI-specific quirk: sends `initialized` before `launch`

### `buildChildStartArgs` (L200–204)
- Always throws (child sessions not supported)

### `shouldDeferParentConfigDone` (L206–210)
- Returns `false`

### `extractLocalVariables` (L212–268)
- Returns `[]` for null/empty stack frames
- Returns `[]` when no scopes for top frame id
- Returns `[]` when scopes present but no `Locals`/`Local` named scope
- Returns `[]` when variables map has no entry for the scope's `variablesReference`
- Extracts from scope named `'Locals'` (L243–250)
- Also recognizes scope named `'Local'` (L252–259)

### `getDebuggerConfiguration` (L270–277)
- `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true`

### `isChildReadyEvent` (L279–294)
- `true` for `{ event: 'initialized' }`
- `false` for other events, and for `null`/`undefined` inputs

### `getDapClientBehavior` (L296–329)
- Returns: `mirrorBreakpointsToChild: false`, `deferParentConfigDone: false`, `pauseAfterChildAttach: false`, `childInitTimeout: 5000`, `suppressPostAttachConfigDone: false`
- `handleReverseRequest` with `command: 'runInTerminal'`: calls `context.sendResponse(request, {})` and returns `{ handled: true }`
- `handleReverseRequest` with any other command: returns `{ handled: false }`, no `sendResponse` call

### `getAdapterSpawnConfig` (L331–372)
- With `adapterCommand` present: uses its `command`, `args`, `env`; passes through `host`, `port`, `logDir`
- Without `adapterCommand`: defaults to `java -cp java/out JdiDapServer --port <port>`

### `validateExecutable` (L398–413)
- Returns `false` for a nonexistent path
- Conditionally tests real `java` binary only in CI/JAVA_HOME environments (soft assertion: just checks `typeof result === 'boolean'`)

## Dependencies
- `JavaAdapterPolicy` — the policy singleton under test, from `@debugmcp/shared`
- `SessionState` — enum with at least `PAUSED`, `RUNNING`, `CREATED` values, from `@debugmcp/shared`
- vitest: `describe`, `it`, `expect`, `vi` (used for `vi.stubEnv`)

## Notable Patterns
- Uses `!` non-null assertions on optional policy methods (`filterStackFrames!`, `isInternalFrame!`, `getAdapterSpawnConfig!`, `validateExecutable!`) — these are optional on the policy interface
- `vi.stubEnv` used for `JAVA_HOME` tests without explicit restore; vitest auto-restores between tests
- `validateExecutable` test at L402 is environment-gated: only runs assertions when `JAVA_HOME` or `CI` is set
