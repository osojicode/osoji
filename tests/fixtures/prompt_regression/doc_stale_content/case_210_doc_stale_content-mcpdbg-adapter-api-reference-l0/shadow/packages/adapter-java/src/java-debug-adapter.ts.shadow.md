# packages\adapter-java\src\java-debug-adapter.ts
@source-hash: 6b2173a3404f0de2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:33Z

## JavaDebugAdapter (L50-572)

Implements `IDebugAdapter` for Java debugging via a JDI bridge (`JdiDapServer`) — a single-file Java program that speaks DAP over TCP using JDI (`com.sun.jdi.*`). The adapter itself does **not** manage TCP connections or forward DAP messages; those responsibilities belong to an external DAP proxy layer. This class handles lifecycle, configuration building, environment validation, DAP event routing, and feature capability reporting.

---

### Key Class

**`JavaDebugAdapter`** (L50–572) extends `EventEmitter`, implements `IDebugAdapter`.

| Property | Type | Notes |
|---|---|---|
| `language` | `DebugLanguage.JAVA` | L51, readonly |
| `name` | `'Java Debug Adapter (JDI)'` | L52, readonly |
| `state` | `AdapterState` | L54, private, starts as `UNINITIALIZED` |
| `currentThreadId` | `number \| null` | L58, updated from DAP `stopped` events |
| `connected` | `boolean` | L59, toggled by `connect()`/`disconnect()` |

---

### Lifecycle (L66–101)

- **`initialize()`** (L68): Validates environment via `validateEnvironment()`. On failure transitions to `ERROR` and throws `AdapterError(ENVIRONMENT_INVALID)`. On success transitions to `READY` and emits `'initialized'`.
- **`dispose()`** (L96): Resets thread/connection state, transitions to `UNINITIALIZED`, emits `'disposed'`.

---

### State Management (L103–123)

- **`getState()`** (L105): Returns current `AdapterState`.
- **`isReady()`** (L109): Returns `true` for `READY`, `CONNECTED`, or `DEBUGGING` states.
- **`getCurrentThreadId()`** (L115): Returns last known stopped thread ID or `null`.
- **`transitionTo()`** (L119, private): Updates state and emits `'stateChanged'` with old/new states.

---

### Environment Validation (L125–183)

- **`validateEnvironment()`** (L127): Checks Java executable presence (`findJavaExecutable`), version (warns if < 11), and JDI bridge compiled state (`resolveJdiBridgeClassDir`). Returns `ValidationResult` with errors/warnings.
- **`getRequiredDependencies()`** (L174): Returns `[{ name: 'JDK', version: '11+', required: true }]`.

---

### Executable Management (L185–198)

- **`resolveExecutablePath(preferredPath?)`** (L187): Delegates to `findJavaExecutable(preferredPath)`.
- **`getDefaultExecutableName()`** (L191): `'java.exe'` on Win32, `'java'` otherwise.
- **`getExecutableSearchPaths()`** (L196): Delegates to `getJavaSearchPaths()`.

---

### Adapter Command Building (L200–255)

- **`buildAdapterCommand(config)`** (L202): Core method. Resolves or compiles JDI bridge directory. Throws `AdapterError(ENVIRONMENT_INVALID)` if bridge unavailable or `config.adapterPort` is falsy/zero. Constructs Java command using `JAVA_HOME` env var if set. Stamps `--owner-pid` using `MCP_DEBUGGER_MAIN_PID` env var (fallback: `process.ppid`) for JVM leak detection. Returns `{ command, args, env }`.
- **`getAdapterModuleName()`** (L253): Returns `'jdi-bridge'`.
- **`getAdapterInstallCommand()`** (L257): Returns `'pnpm --filter @debugmcp/adapter-java run build:adapter'`.

---

### Debug Configuration (L261–353)

- **`transformLaunchConfig(config)`** (L263): Converts `GenericLaunchConfig` to `JavaLaunchConfig`. Sets `type: 'java'`, `request: 'launch'`, `stopOnEntry` (default `true`). Derives `mainClass` from `program` field — strips `.java` extension via `path.basename` if present. Passes through `classpath`, `sourcePath`, `cwd`, `env`, `args`.
- **`getDefaultLaunchConfig()`** (L308): Returns `{ stopOnEntry: true, justMyCode: true }`.
- **`supportsAttach()`** (L317): Returns `true`.
- **`transformAttachConfig(config)`** (L321): Maps `GenericAttachConfig` to `LanguageSpecificAttachConfig` with `type: 'java'`, `request: 'attach'`, host defaults to `'localhost'`.
- **`getDefaultAttachConfig()`** (L348): Returns `{ request: 'attach', host: 'localhost' }`.

---

### DAP Protocol Operations (L355–404)

- **`sendDapRequest()`** (L357): Always throws — DAP request forwarding is handled by the proxy layer, not this adapter.
- **`handleDapEvent(event)`** (L364): Routes DAP events to state transitions and EventEmitter emissions:
  - `stopped` → `DEBUGGING`, captures `threadId`, emits `'stopped'`
  - `continued` → `DEBUGGING`, emits `'continued'`
  - `terminated` → `DISCONNECTED`, emits `'terminated'`
  - `exited`, `thread`, `output`, `breakpoint` → emit corresponding event
- **`handleDapResponse()`** (L402): No-op; handled by proxy layer.

---

### Connection Management (L406–422)

- **`connect(_host, _port)`** (L408): Sets `connected = true`, transitions to `CONNECTED`, emits `'connected'`. Does **not** actually open a TCP connection (proxy layer responsibility).
- **`disconnect()`** (L414): Sets `connected = false`, transitions to `DISCONNECTED`, emits `'disconnected'`.
- **`isConnected()`** (L420): Returns `this.connected`.

---

### Error Handling (L424–478)

- **`getInstallationInstructions()`** (L426): Returns multi-line setup guide string.
- **`getMissingExecutableError()`** (L447): Returns error message for missing Java.
- **`translateErrorMessage(error)`** (L458): Pattern-matches `error.message.toLowerCase()` for `jdi`+`not compiled`, `java`+`not found`, `permission denied`, `classnotfound`/`noclassdef`. Falls through to raw message.

---

### Feature Support (L480–571)

- **`supportsFeature(feature)`** (L482): Returns `true` for: `CONDITIONAL_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `TERMINATE_REQUEST`.
- **`getFeatureRequirements(feature)`** (L493): Returns dependency requirements for conditional/exception breakpoints.
- **`getCapabilities()`** (L517): Returns full `AdapterCapabilities` object. Notable: `supportsConditionalBreakpoints: true`, `supportsEvaluateForHovers: true`, `supportTerminateDebuggee: true`, `supportsTerminateRequest: true`. Most other capabilities are `false`.

---

### Internal Interface

**`JavaLaunchConfig`** (L38–45, private interface): Extends `LanguageSpecificLaunchConfig` with optional `mainClass`, `classpath`, `sourcePath`, `vmArgs`, `javaPath`.

---

### Architectural Notes

- TCP/DAP proxying is entirely external — `sendDapRequest` throws by design (L361).
- `connect()` / `disconnect()` are logical state transitions only; no network I/O.
- Owner PID mechanism (L239): `MCP_DEBUGGER_MAIN_PID` env var enables JVM leak detection across restarts; `process.ppid` is the test fallback.
- JDI bridge is a compiled Java class (`JdiDapServer`) launched as a subprocess; classpath is resolved via `resolveJdiBridgeClassDir()` / `ensureJdiBridgeCompiled()`.
