# packages\adapter-java\src\java-debug-adapter.ts
@source-hash: 6b2173a3404f0de2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:14Z

## JavaDebugAdapter (L50–572)

Implements `IDebugAdapter` for Java debugging via a JDI bridge (`JdiDapServer`) — a single-file Java program that speaks DAP over TCP using `com.sun.jdi.*`. This adapter does **not** handle TCP connections directly; all DAP proxying is delegated to an external proxy layer. Extends `EventEmitter` for lifecycle/debug events.

### Key Class: `JavaDebugAdapter` (L50–572)
- **`readonly language`** = `DebugLanguage.JAVA` (L51)
- **`readonly name`** = `'Java Debug Adapter (JDI)'` (L52)
- **Private state**: `state: AdapterState`, `currentThreadId: number | null`, `connected: boolean`
- **Constructor** (L61–64): Receives `AdapterDependencies` (logger, etc.) — no process spawning here.

### Lifecycle (L66–101)
- **`initialize()`** (L68–94): Validates environment (Java exe + version + JDI bridge), transitions through `INITIALIZING → READY` or `ERROR`. Emits `'initialized'`.
- **`dispose()`** (L96–101): Resets state to `UNINITIALIZED`, emits `'disposed'`.

### State Management (L103–123)
- **`getState()`**, **`isReady()`** (L109–113): Ready if `READY | CONNECTED | DEBUGGING`.
- **`getCurrentThreadId()`**: Returns last stopped thread ID.
- **`transitionTo()`** (L119–123): Private; emits `'stateChanged'` on every transition.

### Environment Validation (L127–183)
- **`validateEnvironment()`** (L127–172): Calls `findJavaExecutable()`, `getJavaVersion()`, `resolveJdiBridgeClassDir()`. Warns if Java < 11 (code `'JAVA_VERSION_OLD'`). Warns if JDI bridge not compiled (code `'JDI_BRIDGE_NOT_COMPILED'`). Errors with `'JAVA_NOT_FOUND'` if Java exe missing.
- **`getRequiredDependencies()`** (L174–183): Returns single `DependencyInfo` for JDK 11+.

### Executable Management (L187–198)
- **`resolveExecutablePath(preferredPath?)`** (L187–189): Delegates to `findJavaExecutable(preferredPath)`.
- **`getDefaultExecutableName()`** (L191–194): `'java.exe'` on win32, `'java'` elsewhere.
- **`getExecutableSearchPaths()`** (L196–198): Delegates to `getJavaSearchPaths()`.

### Adapter Command Building (L202–259)
- **`buildAdapterCommand(config: AdapterConfig)`** (L202–251): Critical method.
  - Resolves JDI bridge dir via `resolveJdiBridgeClassDir()` then falls back to `ensureJdiBridgeCompiled()`. Throws `AdapterError(ENVIRONMENT_INVALID)` if unavailable.
  - Throws if `config.adapterPort` is falsy or 0.
  - Builds java command using `JAVA_HOME/bin/java` (or plain `'java'`).
  - Passes `--owner-pid` from `MCP_DEBUGGER_MAIN_PID` env var or `process.ppid` (zombie JVM reaping).
  - Returns `AdapterCommand { command, args, env }` running `JdiDapServer --port <port> --owner-pid <pid>`.
- **`getAdapterModuleName()`** (L253–255): `'jdi-bridge'`
- **`getAdapterInstallCommand()`** (L257–259): `'pnpm --filter @debugmcp/adapter-java run build:adapter'`

### Debug Configuration (L263–353)
- **`transformLaunchConfig(config)`** (L263–306): Maps `GenericLaunchConfig → JavaLaunchConfig`. Extracts `mainClass` from `.java` filename or program string. Passes through `classpath`, `sourcePath`, `cwd`, `env`, `args`. Sets `stopOnEntry` default to `true`.
- **`getDefaultLaunchConfig()`** (L308–313): `{ stopOnEntry: true, justMyCode: true }`.
- **`supportsAttach()`** (L317–319): Returns `true`.
- **`transformAttachConfig(config)`** (L321–346): Maps host (default `'localhost'`), port, optional `sourcePaths`, `stopOnEntry`, `cwd`, `env`, `timeout`.
- **`getDefaultAttachConfig()`** (L348–353): `{ request: 'attach', host: 'localhost' }`.

### DAP Protocol Operations (L357–404)
- **`sendDapRequest()`** (L357–362): Always throws — DAP forwarding is proxy-layer responsibility.
- **`handleDapEvent(event)`** (L364–400): Switch on `event.event`:
  - `'stopped'` → `DEBUGGING` state, captures `threadId`, emits `'stopped'`
  - `'continued'` → `DEBUGGING` state, emits `'continued'`
  - `'terminated'` → `DISCONNECTED` state, emits `'terminated'`
  - `'exited'`, `'thread'`, `'output'`, `'breakpoint'` → forwarded as events
- **`handleDapResponse()`** (L402–404): No-op (proxy handles responses).

### Connection Management (L408–422)
- **`connect(_host, _port)`** (L408–412): Sets `connected = true`, transitions to `CONNECTED`, emits `'connected'`. Does **not** actually open a TCP connection.
- **`disconnect()`** (L414–418): Sets `connected = false`, transitions to `DISCONNECTED`, emits `'disconnected'`.
- **`isConnected()`** (L420–422): Returns `this.connected` flag.

### Feature Support (L482–571)
- **`supportsFeature(feature)`** (L482–491): Supports `CONDITIONAL_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `EVALUATE_FOR_HOVERS`, `TERMINATE_REQUEST`.
- **`getCapabilities()`** (L517–571): Returns full `AdapterCapabilities` object. Notable: `supportsConditionalBreakpoints: true`, `supportsEvaluateForHovers: true`, `supportTerminateDebuggee: true`, `supportsTerminateRequest: true`. Most advanced features disabled.

### Internal Interface: `JavaLaunchConfig` (L38–45)
Extends `LanguageSpecificLaunchConfig` with optional `mainClass`, `classpath`, `sourcePath`, `vmArgs`, `javaPath`.

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `AdapterState`, `AdapterError`, `AdapterErrorCode`, `DebugLanguage`, `AdapterDependencies`, and all config/validation types.
- `./utils/java-utils.js`: `findJavaExecutable`, `getJavaVersion`, `getJavaSearchPaths`
- `./utils/jdi-resolver.js`: `resolveJdiBridgeClassDir`, `ensureJdiBridgeCompiled`
- `@vscode/debugprotocol`: DAP event/response types

### Architectural Notes
- TCP connection is a **logical stub** only — `connect()` just flips a flag; real networking is handled externally.
- `sendDapRequest()` always throws by design — DAP proxy layer intercepts before this method would be called.
- Owner PID mechanism (`--owner-pid`) enables zombie JVM detection by downstream processes.
- Version parsing (L138–146) handles legacy Java 1.x versioning scheme (`1.8` → effective major 8).