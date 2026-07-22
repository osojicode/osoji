# tests\unit\shared\adapter-policy-dotnet.test.ts
@source-hash: ea4524b8a8c4182e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:14Z

## Unit Tests: DotnetAdapterPolicy

Test suite for `DotnetAdapterPolicy` from `packages/shared/src/interfaces/adapter-policy-dotnet.js`. Exercises all public methods and properties of the dotnet DAP adapter policy object. Uses Vitest with `vi.stubEnv` for environment variable testing and real process execution for `validateExecutable` integration-style tests.

### Test Coverage (L5–434)

Organized into sections via comments:

**Identity (L8–18)**
- `name` is `"dotnet"` (L9)
- `supportsReverseStartDebugging` is `false` (L13)
- `childSessionStrategy` is `"none"` (L17)

**Child Sessions (L22–36)**
- `buildChildStartArgs` throws `/does not support child sessions/` (L23)
- `shouldDeferParentConfigDone()` returns `false` (L27)
- `isChildReadyEvent` returns `true` for `"initialized"` event, `false` for others (L31–36)

**Local Variable Extraction (L40–145)**
- Extracts variables from `"Locals"` scope by matching `variablesReference` (L40–60)
- Default behavior filters compiler-generated variables: names matching `<>`, `CS$<>`, `$VB$Local_`, `<>t__builder`, `<>s__` patterns (L62–87)
- `includeSpecial=true` bypasses filter (L89–106)
- Edge cases: empty frames, missing scopes, empty scopes array, no `"Locals"` scope found, missing variables reference (L108–145)

**Scope and Configuration (L149–162)**
- `getLocalScopeName()` returns `['Locals']` (L150)
- `getDapAdapterConfiguration()` returns `{ type: 'coreclr' }` (L154)
- `getDebuggerConfiguration()`: `requiresStrictHandshake=false`, `skipConfigurationDone=false`, `supportsVariableType=true` (L157–162)

**Executable Resolution (L166–178)**
- Returns provided path directly (L167)
- Falls back to `NETCOREDBG_PATH` env var (L171)
- Defaults to `"netcoredbg"` string when neither provided (L175–178)

**Session Readiness (L182–186)**
- `isSessionReady` returns `true` only for `SessionState.PAUSED`

**Command Queueing (L190–198)**
- `requiresCommandQueueing()` returns `false` (L191)
- `shouldQueueCommand()` returns `{ shouldQueue: false, shouldDefer: false }` (L195–198)

**State Management (L202–237)**
- `createInitialState()` produces `{ initialized: false, configurationDone: false }` (L202–206)
- `updateStateOnCommand('configurationDone', ...)` sets `state.configurationDone = true` (L208–212)
- `updateStateOnCommand` ignores non-`configurationDone` commands (L214–218)
- `updateStateOnEvent('initialized', ...)` sets `state.initialized = true` (L220–224)
- `updateStateOnEvent` ignores other events (L226–230)
- `isInitialized(state)` and `isConnected(state)` both reflect `state.initialized` (L232–244)

**Adapter Matching (L248–270)**
- `matchesAdapter` returns `true` if `command` or `args` contain `"netcoredbg"` or `"dotnet"` (L248–264)
- Returns `false` for unrelated adapters (L266–270)

**Initialization Behavior (L274–282)**
- `sendAttachBeforeInitialized=false`, `sendLaunchBeforeConfig=true` (netcoredbg sends `initialized` before `launch` ack) (L274–282)

**DAP Client Behavior (L286–315)**
- Default fields: `mirrorBreakpointsToChild=false`, `deferParentConfigDone=false`, `pauseAfterChildAttach=false`, `suppressPostAttachConfigDone=false`, `childInitTimeout=5000` (L286–293)
- `handleReverseRequest` with `command="runInTerminal"`: calls `context.sendResponse(request, {})`, returns `{ handled: true }` (L295–305)
- Unknown reverse request: returns `{ handled: false }`, does not call `sendResponse` (L307–315)

**Stack Frame Filtering (L319–355)**
- `filterStackFrames(frames, false)` removes frames with empty `file` and frames with names starting with `System.*` or `Microsoft.*` (L319–344)
- `filterStackFrames(frames, true)` (includeInternals) returns all frames (L346–355)

**isInternalFrame (L359–373)**
- `true` for empty `file`, `System.*` names, `Microsoft.*` names (L359–369)
- `false` for user frames with non-empty file and non-system namespaces (L371–373)

**Adapter Spawn Config (L377–419)**
- With `adapterCommand`: uses its `command`, `args`, `env`; inherits `host`/`port` from payload (L377–392)
- Without `adapterCommand`, with `executablePath`: uses path as command, appends `--interpreter=vscode` and `--server=<port>` (L394–407)
- No `executablePath` fallback: defaults to `"netcoredbg"` (L409–419)

**validateExecutable (L423–434)**
- Integration-style tests: `process.execPath` (node) validates as `true`, nonexistent command validates as `false` (L424–433), both with 10 s timeout

### Dependencies
- `DotnetAdapterPolicy`: the object under test (imported from shared package, L2)
- `SessionState`: enum used in `isSessionReady` tests (L3, L183–185)
- `vi.stubEnv`: mocks `NETCOREDBG_PATH` environment variable (L171, L176)
