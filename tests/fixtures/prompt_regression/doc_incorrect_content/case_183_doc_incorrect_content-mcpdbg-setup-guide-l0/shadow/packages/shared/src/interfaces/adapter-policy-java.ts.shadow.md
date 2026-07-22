# packages\shared\src\interfaces\adapter-policy-java.ts
@source-hash: c72754605e965ff7
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:08Z

## JavaAdapterPolicy (L14-249)

Implements `AdapterPolicy` for the Java Debug Adapter (JDI bridge / JdiDapServer), which communicates over TCP using JDI (Java Debug Interface) natively via the DAP protocol.

### Key Architectural Decision: Non-Standard Init Ordering
JdiDapServer emits `initialized` during the `initialize` handshake — *before* the `launch` request. The `getInitializationBehavior()` method (L170-174) returns `{ sendLaunchBeforeConfig: true }` to signal this non-standard ordering to the proxy: wait for `initialized`, then send `launch`, then breakpoints + `configurationDone`.

### Policy Methods

| Method | Lines | Description |
|---|---|---|
| `isNonFileSourceIdentifier` | L26-32 | Detects Java FQCNs (e.g. `com.example.MyClass`, `com.example.Outer$Inner`) — no path separators, no `.java` extension |
| `extractLocalVariables` | L34-61 | Extracts variables from top stack frame using `Locals` or `Local` scope name (JDI bridge convention) |
| `getLocalScopeName` | L63-65 | Returns `['Locals']` — JDI bridge scope name |
| `getDapAdapterConfiguration` | L67-71 | Returns `{ type: 'java' }` |
| `resolveExecutablePath` | L73-85 | Returns provided path, or constructs path from `JAVA_HOME` env var, or falls back to `'java'` |
| `getDebuggerConfiguration` | L87-93 | `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true` |
| `isSessionReady` | L95 | Ready only when `SessionState.PAUSED` |
| `validateExecutable` | L97-118 | Spawns `java -version`, checks exit code 0 AND has stdout/stderr output |
| `requiresCommandQueueing` | L120 | Always returns `false` |
| `shouldQueueCommand` | L122-128 | Returns `{ shouldQueue: false, shouldDefer: false }` |
| `createInitialState` | L130-135 | `{ initialized: false, configurationDone: false }` |
| `updateStateOnCommand` | L137-141 | Sets `state.configurationDone = true` when command is `'configurationDone'` |
| `updateStateOnEvent` | L143-147 | Sets `state.initialized = true` when event is `'initialized'` |
| `isInitialized` | L149-151 | Returns `state.initialized` |
| `isConnected` | L153-155 | Returns `state.initialized` (same as `isInitialized`) |
| `matchesAdapter` | L157-165 | Matches if command/args contain `jdidapserver`, `jdi-bridge`, or `java-debug` (case-insensitive) |
| `getInitializationBehavior` | L170-174 | Returns `{ sendLaunchBeforeConfig: true }` — critical for JDI non-standard ordering |
| `getDapClientBehavior` | L176-194 | Handles `runInTerminal` reverse requests; no child routing, no mirror breakpoints, 5000ms child init timeout |
| `filterStackFrames` | L196-215 | Filters JDK internals (frames starting with `java.`, `javax.`, `sun.`, or paths containing `/jdk/`, `/rt.jar/`) unless `includeInternals` is true |
| `isInternalFrame` | L217-220 | Checks if frame name starts with `java.`, `javax.`, or `sun.` |
| `getAdapterSpawnConfig` | L222-248 | If `payload.adapterCommand` provided, uses it; otherwise defaults to spawning `java -cp java/out JdiDapServer --port <port>` |

### Static Fields
- `name: 'java'` (L15)
- `supportsReverseStartDebugging: false` (L16)
- `childSessionStrategy: 'none'` (L17)
- `shouldDeferParentConfigDone: () => false` (L18)
- `buildChildStartArgs`: throws — child sessions not supported (L19-21)
- `isChildReadyEvent`: returns `true` when `evt.event === 'initialized'` (L22-24)

### Dependencies
- `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` from `./adapter-policy.js`
- `SessionState` from `@debugmcp/shared`
- `StackFrame`, `Variable` from `../models/index.js`
- `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult` from `./dap-client-behavior.js`
- `DebugProtocol` from `@vscode/debugprotocol`
- `child_process.spawn` (dynamically imported in `validateExecutable`)
