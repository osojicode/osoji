# packages\adapter-dotnet\src\DotnetDebugAdapter.ts
@source-hash: 543cad98cc9a2e2f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:32Z

## DotnetDebugAdapter

Primary implementation of `IDebugAdapter` for .NET/C# debugging via **netcoredbg**. Extends `EventEmitter` and provides the full lifecycle, configuration, and protocol-handling surface needed by the proxy layer. All actual DAP message transport is delegated to `ProxyManager`; this class handles discovery, configuration transformation, PDB conversion, and process-arch detection.

### Key Architecture Notes

- **Bridge pattern** (L292–330): Instead of netcoredbg's `--server=PORT` TCP mode (which has a connection bug), the adapter spawns a `netcoredbg-bridge.js` shim that bridges TCP↔stdio. `buildAdapterCommand` resolves the bridge from 6 candidate paths in priority order.
- **PDB conversion** (L395–406): On attach, Windows PDBs are auto-converted to Portable PDB format via bundled `Pdb2Pdb.exe` into a temp dir, since netcoredbg only reads Portable PDBs.
- **Architecture detection** (L378–383): Before resolving the netcoredbg executable, `transformAttachConfig` calls `getProcessArchitecture` to detect if the target is x86/x64. The arch suffix is used as a cache-key discriminant in `resolveExecutablePath`.
- **Safety invariant**: `terminateDebuggee` is hardcoded to `false` (L415) in attach configs and `supportTerminateDebuggee: false` (L617) in capabilities, so long-running processes like NinjaTrader are never killed on detach.
- **`sendDapRequest` stub** (L436–455): Only validates `.NET` exception filter names; returns `{}` — real DAP I/O is in ProxyManager, not here.

### Classes

#### `DotnetDebugAdapter` (L105–638)
Implements `IDebugAdapter`, extends `EventEmitter`.

| Member | Lines | Role |
|--------|-------|------|
| `language` | L106 | `DebugLanguage.DOTNET` (readonly) |
| `name` | L107 | Display name (readonly) |
| `state` | L109 | `AdapterState`, internal FSM |
| `debuggerPathCache` | L113 | `Map<string, DebuggerPathCacheEntry>` — 60 s TTL cache for netcoredbg paths |
| `cacheTimeout` | L114 | 60,000 ms |
| `currentThreadId` | L117 | Last stopped thread ID from DAP events |
| `connected` | L118 | Tracks logical connection state |
| `targetProcessArch` | L119 | `'x86' \| 'x64' \| null` — set during attach config |
| `initialize()` | L128–147 | Validates environment, transitions to READY or ERROR, emits `'initialized'` |
| `dispose()` | L149–156 | Clears cache and state, emits `'disposed'` |
| `getState()` | L160–162 | Returns current `AdapterState` |
| `isReady()` | L164–168 | True if READY, CONNECTED, or DEBUGGING |
| `getCurrentThreadId()` | L170–172 | Returns last stopped threadId |
| `transitionTo()` | L174–178 | Private FSM helper; emits `'stateChanged'` |
| `validateEnvironment()` | L182–205 | Checks netcoredbg reachability; returns `ValidationResult` |
| `getRequiredDependencies()` | L207–222 | Lists netcoredbg (required) and .NET Runtime (optional) |
| `resolveExecutablePath()` | L226–248 | Finds netcoredbg binary with arch-aware caching |
| `getDefaultExecutableName()` | L250–252 | Returns `'netcoredbg'` |
| `getExecutableSearchPaths()` | L254–279 | Platform-specific search path list |
| `buildAdapterCommand()` | L292–330 | Builds Node command to run the TCP-to-stdio bridge |
| `transformLaunchConfig()` | L342–354 | Converts `GenericLaunchConfig` → `DotnetLaunchConfig` with `type:'coreclr'` |
| `getDefaultLaunchConfig()` | L356–363 | Defaults: stopOnEntry=true, justMyCode=true, cwd=process.cwd() |
| `transformAttachConfig()` | L375–425 | Detects arch, scans PDBs, runs Pdb2Pdb conversion, builds attach config |
| `getDefaultAttachConfig()` | L427–432 | Defaults: stopOnEntry=false, justMyCode=true |
| `sendDapRequest()` | L436–455 | Validates exception filter names; returns stub `{}` |
| `handleDapEvent()` | L457–464 | Tracks `stopped` threadId; re-emits all DAP events |
| `handleDapResponse()` | L466–468 | No-op |
| `connect()` | L472–478 | Sets connected=true, transitions to CONNECTED, emits `'connected'` |
| `disconnect()` | L480–485 | Clears state, transitions to DISCONNECTED |
| `isConnected()` | L487–489 | Returns `this.connected` |
| `getInstallationInstructions()` | L493–506 | Multi-line setup instructions string |
| `getMissingExecutableError()` | L508–513 | Error message when netcoredbg not found |
| `translateErrorMessage()` | L515–539 | Maps common error substrings to user-friendly messages |
| `supportsFeature()` | L543–557 | Checks against a static supported-features list |
| `getFeatureRequirements()` | L559–581 | Returns Portable PDB requirements for conditional/exception breakpoints |
| `getCapabilities()` | L583–637 | Full `AdapterCapabilities` object for DAP Initialize response |

### Internal Interfaces

#### `DebuggerPathCacheEntry` (L76–79)
`{ path: string; timestamp: number }` — used as values in `debuggerPathCache`.

#### `DotnetLaunchConfig` (L84–100)
Extends `LanguageSpecificLaunchConfig`; adds `type`, `request`, `program`, `args`, `cwd`, `env`, `justMyCode`, `stopOnEntry`, `console`, `sourceFileMap`, `symbolOptions`.

### Dependencies

- `@debugmcp/shared`: `IDebugAdapter`, all adapter type/enum imports
- `./utils/dotnet-utils.js`: `findNetcoredbgExecutable`, `findPdb2PdbExecutable`, `convertPdbsToTemp`, `getProcessExecutableDir`, `getProcessArchitecture`
- `@vscode/debugprotocol`: DAP protocol types
- Node builtins: `events`, `fs`, `path`, `url`

### Exception Filter Identifiers
Valid .NET exception filters enforced in `sendDapRequest`: `'all'` and `'user-unhandled'` (L443–449).
