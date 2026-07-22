# packages\shared\src\interfaces\adapter-policy.ts
@source-hash: f776792635d240be
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:55Z

## Adapter Policy Contracts

Defines the `AdapterPolicy` interface and supporting types that allow the DAP transport core to remain generic while adapter-specific quirks are encapsulated in policy objects. Consumed by proxy/minimal-dap workers to drive session lifecycle decisions.

### Core Types

**`ChildSessionStrategy`** (L21–25) — Union type discriminant for how child sessions are created:
- `'none'` — no child session
- `'launchWithPendingTarget'` — js-debug pattern using `__pendingTargetId`
- `'attachByPort'` — connect via known inspector port
- `'adoptInParent'` — reuse parent session

**`CommandHandling`** (L30–34) — Result shape returned by `shouldQueueCommand`; signals whether a DAP command should be queued (`shouldQueue`) or deferred (`shouldDefer`) with an optional diagnostic `reason`.

**`AdapterSpecificState`** (L39–43) — Minimum mutable state tracked per adapter. Open-ended via `[key: string]: unknown` index signature. Required fields: `initialized`, `configurationDone`.

### `AdapterPolicy` Interface (L45–354)

The central contract. Implementations cover:

| Method/Property | Line | Role |
|---|---|---|
| `name` | L49 | Diagnostic label |
| `supportsReverseStartDebugging` | L54 | Adapter capability flag |
| `childSessionStrategy` | L59 | Selects child session creation path |
| `shouldDeferParentConfigDone()` | L66 | Controls configDone timing |
| `buildChildStartArgs()` | L72–75 | Produces child launch/attach request |
| `isChildReadyEvent()` | L82 | Determines child session readiness from DAP event |
| `filterStackFrames?()` | L92 | Optional frame filtering |
| `isInternalFrame?()` | L101 | Classifies frames as internal |
| `extractLocalVariables?()` | L113–118 | Language-specific local variable extraction |
| `getLocalScopeName?()` | L126 | Scope name(s) for locals ("Locals", "Local", etc.) |
| `getDapAdapterConfiguration()` | L134–137 | Returns DAP adapter `type` string |
| `resolveExecutablePath()` | L147 | Language runtime path resolution |
| `getDebuggerConfiguration()` | L155–160 | Debugger capability flags |
| `isSessionReady?()` | L166–169 | Custom session-ready predicate |
| `isNonFileSourceIdentifier?()` | L179 | Adapter-specific non-file source handling (e.g., Java FQCNs) |
| `validateExecutable?()` | L188 | Async executable validation |
| `performHandshake?()` | L208–216 | Owns full DAP init sequence for command-queuing policies |
| `requiresCommandQueueing()` | L222 | Adapter command queueing flag |
| `shouldQueueCommand()` | L230 | Per-command queue decision |
| `processQueuedCommands?()` | L238–241 | Reorders queued commands pre-execution |
| `createInitialState()` | L247 | Factory for fresh `AdapterSpecificState` |
| `updateStateOnCommand?()` | L255 | State mutation on DAP command sent |
| `updateStateOnResponse?()` | L263 | State mutation on DAP response received |
| `updateStateOnEvent?()` | L271 | State mutation on DAP event received |
| `isInitialized()` | L278 | Ready-for-commands check |
| `isConnected()` | L285 | Connection-ready check |
| `matchesAdapter()` | L292 | Policy applicability predicate |
| `getInitializationBehavior()` | L299–317 | Composite initialization quirk flags (deferConfigDone, addRuntimeExecutable, sendLaunchBeforeConfig, sendAttachBeforeInitialized, etc.) |
| `getDapClientBehavior()` | L324 | DAP client behavior config (reverse requests, child sessions) |
| `getEvaluateContext?()` | L331 | Evaluate context string for expression evaluation |
| `getAttachBehavior?()` | L340 | Attach-mode tweaks (pauseAfterAttach) |
| `getAdapterSpawnConfig?()` | L353 | Returns spawn or connect configuration |

### `AdapterSpawnPayload`** (L359–367) — Input to `getAdapterSpawnConfig`. Contains `executablePath`, `adapterHost`, `adapterPort`, `logDir`, `scriptPath`, optional `launchConfig`, and optional `adapterCommand`.

### `AdapterSpawnConfig`** (L374–390) — Discriminated union on `mode`:
- `'spawn'`: worker spawns adapter process then connects to `host:port`; includes `command`, `args`, optional `cwd`/`env`
- `'connect'`: external DAP server already listening; only `host`, `port`, `logDir`

### `DefaultAdapterPolicy`** (L398–429) — Exported singleton constant implementing `AdapterPolicy` as a safe placeholder active while the worker selects a concrete policy. Key behaviors:
- `supportsReverseStartDebugging: false`
- `childSessionStrategy: 'none'`
- `buildChildStartArgs` throws — not usable for real sessions
- `requiresCommandQueueing` → `false`
- `isInitialized`/`isConnected`/`matchesAdapter` → `false`
- `getDapClientBehavior` returns `{}`

### Architectural Notes

- `performHandshake` (L208): when defined, the policy **owns** the full DAP start sequence; the proxy worker's built-in flow is bypassed. Attach vs launch is distinguished by `dapLaunchArgs.request === 'attach'`.
- `proxyManager` and `breakpoints` in `performHandshake` context are typed as `unknown`/`Map<string, unknown>` to avoid circular dependencies; concrete types are resolved in implementation.
- `resolveExecutablePath` and `getAdapterSpawnConfig` accept optional `platform`/`arch` overrides specifically for test isolation (issues #183, #186).
- The interface deliberately keeps optional methods (`?`) for adapter-specific extensions to avoid forcing all policies to implement every behavior.