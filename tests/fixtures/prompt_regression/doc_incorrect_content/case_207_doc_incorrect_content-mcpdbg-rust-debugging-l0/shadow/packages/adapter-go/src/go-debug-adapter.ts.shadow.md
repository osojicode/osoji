# packages\adapter-go\src\go-debug-adapter.ts
@source-hash: 5df41d0ce3f80c23
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## Go Debug Adapter (`go-debug-adapter.ts`)

### Purpose
Implements the `IDebugAdapter` interface for Go debugging using Delve (dlv) via the Debug Adapter Protocol (DAP). Manages lifecycle, environment validation, executable resolution, launch config transformation, DAP event handling, and feature capability reporting for Go/Delve.

---

### Key Interfaces

#### `GoPathCacheEntry` (L42–46)
Internal cache structure for Go/Delve executable paths. Fields: `path`, `timestamp`, `version?`. Used in both `goPathCache` and `delvePathCache`.

#### `GoLaunchConfig` (L51–65)
Extends `LanguageSpecificLaunchConfig` with Go-specific fields: `mode` (`'debug' | 'test' | 'exec' | 'replay' | 'core'`), `program`, `buildFlags`, `output`, `dlvCwd`, `backend`, `stackTraceDepth`, `showGlobalVariables`, `showRegisters`, `hideSystemGoroutines`, `goroutineFilters`, `substitutePath`.

---

### Main Class: `GoDebugAdapter` (L70–639)
Extends `EventEmitter`, implements `IDebugAdapter`.

**Constants/Properties:**
- `language = DebugLanguage.GO` (L71)
- `name = 'Go Debug Adapter (Delve)'` (L72)
- `cacheTimeout = 60000` ms (L80) — TTL for both Go and Delve path caches
- `goPathCache: Map<string, GoPathCacheEntry>` (L78) — caches Go binary paths/versions
- `delvePathCache: Map<string, GoPathCacheEntry>` (L79) — caches Delve binary paths/versions
- `currentThreadId: number | null` (L83) — set on DAP `stopped` events
- `connected: boolean` (L84)

---

### Method Summary

#### Lifecycle
- **`constructor(dependencies)`** (L86–89): Stores `AdapterDependencies` (used for `logger`).
- **`initialize()`** (L93–121): Transitions UNINITIALIZED → INITIALIZING → READY (or ERROR). Calls `validateEnvironment()`; throws `AdapterError(ENVIRONMENT_INVALID)` on failure. Emits `'initialized'`.
- **`dispose()`** (L123–130): Clears caches, resets state/connection. Emits `'disposed'`.

#### State Management
- **`getState()`** (L134–136): Returns current `AdapterState`.
- **`isReady()`** (L138–142): `true` when state is READY, CONNECTED, or DEBUGGING.
- **`getCurrentThreadId()`** (L144–146): Returns last thread ID from `stopped` event.
- **`transitionTo(newState)`** (L148–152): Updates `state`, emits `'stateChanged'`.

#### Environment Validation
- **`validateEnvironment()`** (L156–222): Async checks for Go ≥ 1.18 and Delve with DAP support. Returns `ValidationResult` with errors/warnings. Error codes: `GO_NOT_FOUND`, `GO_VERSION_TOO_OLD`, `GO_VERSION_CHECK_FAILED`, `DELVE_NOT_INSTALLED`, `DELVE_DAP_NOT_SUPPORTED`.
- **`getRequiredDependencies()`** (L224–239): Returns Go 1.18+ and Delve (latest) as required deps.

#### Executable Management
- **`resolveExecutablePath(preferredPath?)`** (L243–263): Resolves Delve (`dlv`) path with 1-minute cache. Key `'default'` used when no preferred path.
- **`getDefaultExecutableName()`** (L265–267): Returns `'dlv.exe'` on win32, else `'dlv'`.
- **`getExecutableSearchPaths()`** (L269–271): Delegates to `getGoSearchPaths()` from utils.

#### Adapter Configuration
- **`buildAdapterCommand(config)`** (L275–294): Builds `dlv dap --listen=host:port` command. Adds `--log --log-output=dap` if `process.env.DEBUG` is set. Falls back to `'dlv'` if no `executablePath` in config.
- **`getAdapterModuleName()`** (L296–298): Returns `'dlv'`.
- **`getAdapterInstallCommand()`** (L300–302): Returns `go install github.com/go-delve/delve/cmd/dlv@latest`.

#### Debug Configuration
- **`transformLaunchConfig(config)`** (L306–350): Converts `GenericLaunchConfig` to `GoLaunchConfig`. Auto-infers `mode`: `.go` source → `'debug'`, otherwise → `'exec'`; explicit user `mode` overrides. Sets `stopOnEntry: false` by default. Maps `cwd` → `dlvCwd`. Hardcodes `stackTraceDepth=50`, `showGlobalVariables=false`, `hideSystemGoroutines=true`.
- **`getDefaultLaunchConfig()`** (L352–357): Returns `{ stopOnEntry: false, justMyCode: true }`.

#### DAP Protocol Operations
- **`sendDapRequest()`** (L361–366): Always throws — not implemented (handled by DAP client).
- **`handleDapEvent(event)`** (L368–406): Routes DAP events to state transitions and re-emits. `stopped` → DEBUGGING + captures `threadId`; `continued` → DEBUGGING; `terminated` → DISCONNECTED; others re-emitted directly.
- **`handleDapResponse()`** (L408–410): No-op.

#### Connection Management
- **`connect()`** (L414–418): Sets `connected=true`, transitions to CONNECTED, emits `'connected'`.
- **`disconnect()`** (L420–424): Sets `connected=false`, transitions to DISCONNECTED, emits `'disconnected'`.
- **`isConnected()`** (L426–428): Returns `this.connected`.

#### Error Handling
- **`getInstallationInstructions()`** (L432–453): Multi-line install guide string for Go + Delve.
- **`getMissingExecutableError()`** (L456–467): Error string for missing Go binary.
- **`translateErrorMessage(error)`** (L469–493): Maps known error message substrings to user-friendly messages. Checks for `dlv not found`, `go not found`, `permission denied`, `could not launch process`, `could not attach`.

#### Feature Support
- **`supportsFeature(feature)`** (L497–512): Supported: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `EXCEPTION_BREAKPOINTS`, `VARIABLE_PAGING`, `EVALUATE_FOR_HOVERS`, `SET_VARIABLE`, `LOG_POINTS`, `TERMINATE_REQUEST`, `LOADED_SOURCES_REQUEST`, `STEP_IN_TARGETS_REQUEST`.
- **`getFeatureRequirements(feature)`** (L514–544): Returns version/config requirements per feature.
- **`getCapabilities()`** (L546–601): Full `AdapterCapabilities` object. Notable: `supportsStepBack: false` (requires `rr`), exception breakpoint filters for `panic` and `fatal`.

#### Private/Go-specific Helpers
- **`checkGoVersion(goPath)`** (L608–621): Cached wrapper around `getGoVersion()`. Returns version string or `null`.
- **`checkDelveVersion(dlvPath)`** (L626–639): Public cached wrapper around `getDelveVersion()`. Returns version string or `null`.

---

### Events Emitted
| Event | When |
|-------|------|
| `'initialized'` | Successful `initialize()` |
| `'disposed'` | `dispose()` |
| `'stateChanged'` | Any state transition |
| `'stopped'` | DAP `stopped` event |
| `'continued'` | DAP `continued` event |
| `'terminated'` | DAP `terminated` event |
| `'exited'` | DAP `exited` event |
| `'thread'` | DAP `thread` event |
| `'output'` | DAP `output` event |
| `'breakpoint'` | DAP `breakpoint` event |
| `'connected'` | `connect()` |
| `'disconnected'` | `disconnect()` |

---

### Dependencies
- **`@vscode/debugprotocol`**: DAP type definitions
- **`@debugmcp/shared`**: Core interfaces (`IDebugAdapter`, `AdapterState`, `AdapterError`, `AdapterErrorCode`, `DebugLanguage`, `AdapterDependencies`, etc.)
- **`./utils/go-utils.js`**: `findGoExecutable`, `findDelveExecutable`, `getGoVersion`, `getDelveVersion`, `checkDelveDapSupport`, `getGoSearchPaths`

---

### Architectural Notes
- **CI-mode logging**: Uses `process.env.CI === 'true'` to emit diagnostic `console.error` calls during `initialize()` and `validateEnvironment()` — not for production logging.
- **Dual caches**: Separate `Map`-based caches for Go and Delve paths, both with 60s TTL.
- **No actual DAP transport**: `sendDapRequest` always throws; the adapter is a configuration/lifecycle layer — actual DAP communication is delegated to a ProxyManager.
- **Mode inference**: Auto-detects `debug` vs `exec` mode based on `.go` file extension; user-specified mode always wins.
