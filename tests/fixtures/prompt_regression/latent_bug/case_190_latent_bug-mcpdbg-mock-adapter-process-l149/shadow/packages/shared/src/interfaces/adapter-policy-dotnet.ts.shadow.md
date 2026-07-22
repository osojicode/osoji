# packages\shared\src\interfaces\adapter-policy-dotnet.ts
@source-hash: d80e5f7af591be9a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:06Z

## Purpose

Defines `DotnetAdapterPolicy`, the singleton `AdapterPolicy` implementation for the .NET debug adapter (netcoredbg). Encodes all netcoredbg-specific DAP proxy behaviors including variable filtering, stack frame filtering, adapter spawn configuration, and state tracking.

## Key Export

### `DotnetAdapterPolicy` (L42–324) — `AdapterPolicy`

A constant object literal implementing the `AdapterPolicy` interface. Selected by `selectPolicy()` in `session-manager-data.ts` when session language is `'dotnet'`.

**Identity & child session** (L43–52):
- `name: 'dotnet'`
- `supportsReverseStartDebugging: false`
- `childSessionStrategy: 'none'` — throws if `buildChildStartArgs` is called
- `isChildReadyEvent`: returns true when `evt.event === 'initialized'`

**Variable extraction** — `extractLocalVariables` (L57–109):
- Looks up top stack frame → finds scope named `'Locals'` or `'Local'`
- When `includeSpecial=false` (default), filters out compiler-generated variables:
  - C# generated: prefix `<>` (L90–92)
  - Closure variables: prefix `CS$<>` (L95–97)
  - VB.NET generated: prefix `$VB$` (L100–102)

**Scope naming** — `getLocalScopeName` (L115–117): returns `['Locals']`
> Note: `extractLocalVariables` also checks `'Local'` as fallback (L76) but `getLocalScopeName` only returns `'Locals'`.

**Adapter configuration** — `getDapAdapterConfiguration` (L124–128): returns `{ type: 'coreclr' }`

**Executable resolution** — `resolveExecutablePath` (L130–142):
1. Use `providedPath` if given
2. Fall back to `process.env.NETCOREDBG_PATH`
3. Default to `'netcoredbg'` string (relies on downstream `findNetcoredbgExecutable`)

**Debugger config** — `getDebuggerConfiguration` (L144–150):
- `requiresStrictHandshake: false`, `skipConfigurationDone: false`, `supportsVariableType: true`

**Session readiness** — `isSessionReady` (L152): returns `true` when `state === SessionState.PAUSED`

**Validation** — `validateExecutable` (L157–179): spawns `netcoredbg --version`, resolves `true` if exit code is 0 OR any stdout/stderr output was received.

**Command queueing** (L181–189): `requiresCommandQueueing` always returns `false`; `shouldQueueCommand` returns `{ shouldQueue: false, shouldDefer: false }`.

**State management** (L191–216):
- `createInitialState`: `{ initialized: false, configurationDone: false }`
- `updateStateOnCommand`: sets `state.configurationDone = true` on `'configurationDone'` command
- `updateStateOnEvent`: sets `state.initialized = true` on `'initialized'` event
- `isInitialized` / `isConnected`: both return `state.initialized`

**Adapter matching** — `matchesAdapter` (L218–225): checks command/args strings (lowercased) contain `'netcoredbg'` or `'dotnet'`

**Initialization behavior** — `getInitializationBehavior` (L227–236):
- `sendLaunchBeforeConfig: true` — netcoredbg fires `initialized` event immediately after `initialize` response; launch must precede `configurationDone`
- `sendAttachBeforeInitialized: false`

**DAP client behavior** — `getDapClientBehavior` (L238–256):
- Handles `runInTerminal` reverse requests (responds with empty body, `handled: true`)
- All child-session/multi-session fields disabled (`mirrorBreakpointsToChild: false`, `deferParentConfigDone: false`, etc.)

**Stack frame filtering** — `filterStackFrames` (L261–282):
- When `includeInternals=false`: drops frames with no file path and frames starting with `System.` or `Microsoft.`

**Internal frame check** — `isInternalFrame` (L284–288): same logic as filter

**Spawn config** — `getAdapterSpawnConfig` (L297–324):
- Primary path: if `payload.adapterCommand` exists, use TCP-to-stdio bridge command
- Fallback: spawn `netcoredbg` directly with `--interpreter=vscode --server=<port>` (noted as potentially broken on Windows due to server mode bug)

## Dependencies

| Import | Used For |
|---|---|
| `@vscode/debugprotocol` | `DebugProtocol.Event`, `DebugProtocol.Scope`, `DebugProtocol.Request` types |
| `./adapter-policy.js` | `AdapterPolicy`, `AdapterSpecificState`, `CommandHandling` interfaces |
| `@debugmcp/shared` (SessionState) | `SessionState.PAUSED` enum value in `isSessionReady` |
| `../models/index.js` | `StackFrame`, `Variable` model types |
| `./dap-client-behavior.js` | `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult` types |
| `child_process` (dynamic) | Used inside `validateExecutable` to spawn netcoredbg |

## Architectural Notes

- **No runtime state**: this is a pure policy singleton; all state is passed in and returned
- **TCP bridge by default**: `getAdapterSpawnConfig` favors the bridge command over direct netcoredbg stdio due to a known `--server=PORT` bug
- **terminateDebuggee always false** on detach from attached processes (documented in file header, enforced upstream)
- **VB.NET support**: `$VB$` prefix filter (L100–102) indicates multi-language .NET support beyond C#
