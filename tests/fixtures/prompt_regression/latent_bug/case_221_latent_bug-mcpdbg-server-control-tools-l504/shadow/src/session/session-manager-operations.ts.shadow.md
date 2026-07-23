# src\session\session-manager-operations.ts
@source-hash: 5dc0d9d7c3837b52
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:08Z

## SessionManagerOperations (L62–2057)

Abstract class providing debug operation methods for DAP-based session management. Extends `SessionManagerData` (which provides logger, sessionStore, fileSystem, adapterRegistry, proxyManagerFactory, selectPolicy, etc.). Intended to be further extended by a concrete class that also mixes in lifecycle/state methods.

---

### Exported Interfaces

**`EvaluateResult`** (L36–45)  
Return type for `evaluateExpression`. Fields: `success`, `result`, `type`, `variablesReference`, `namedVariables`, `indexedVariables`, `presentationHint`, `error`.

**`RedefineClassesResult`** (L47–57)  
Return type for `redefineClasses`. Fields: `success`, `redefined`, `redefinedCount`, `skippedNotLoaded`, `failedCount`, `failed`, `scannedFiles`, `newestTimestamp`, `error`.

---

### Protected Timing Constants (configurable by tests/subclasses)

| Property | Default | Purpose |
|---|---|---|
| `attachVerifyTimeoutMs` | 5000ms | Max time polling DAP `threads` after attach handshake |
| `attachVerifyIntervalMs` | 250ms | Poll interval between thread checks |
| `attachPauseStopTimeoutMs` | 5000ms | Wait for `stopped` event after post-attach pause |
| `stepGraceMs` | 5000ms | Grace window before returning `pending: true` on step |
| `pauseGraceMs` | 5000ms | Grace window before returning `pending: true` on pause |

---

### Key Methods

**`startProxyManager`** (L93–348, `protected async`)  
Core setup: creates session log dir, resolves adapter via `adapterRegistry.create`, calls `transformLaunchConfig` or `transformAttachConfig`, resolves executable path, builds `ProxyConfig`, creates ProxyManager via factory, attaches event handlers, starts proxy. Handles toolchain validation — throws `Error('MSVC_TOOLCHAIN_DETECTED')` with `.toolchainValidation` if incompatible. Returns final `LanguageSpecificLaunchConfig`.

**`startDebugging`** (L411–798, `public async`)  
Orchestrates a full debug launch. Calls `startProxyManager`, invokes `policy.performHandshake` if available, then waits for session to reach a ready state (`stopped`, `adapter-configured`, `terminated`, or 30s timeout). Handles dry-run path (polls `dry-run-complete` event with `dryRunTimeoutMs`). Returns `DebugResult`. On error, captures proxy log tail (last 80 lines) for diagnostics; handles `MSVC_TOOLCHAIN_DETECTED` specially by reverting lifecycle to `CREATED`.

**`setBreakpoint`** (L801–901, `public async`)  
Creates a `Breakpoint` with `uuidv4`, stores in `session.breakpoints` map. If proxy is active and session is RUNNING/PAUSED, sends `setBreakpoints` DAP request with **all** breakpoints for the same file (DAP replace-all semantics). Adds `.NET PDB format hint` to "no symbols" messages. Returns the new `Breakpoint`.

**`stepOver`** / **`stepInto`** / **`stepOut`** (L903–1027, `public async`)  
Guard: session must be PAUSED and proxy running. Delegates to `_executeStepOperation` with DAP commands `next` / `stepIn` / `stepOut`. Returns `DebugResult`.

**`_executeStepOperation`** (L1029–1149, `private`)  
Core step logic. Sends DAP command, listens for `stopped`/`terminated`/`exited`/`exit` events. On `stopped`, fetches stack trace via `getStackTrace` to capture current location. If no event within `stepGraceMs`, returns `{ success: true, data: { pending: true } }`. Thread-safe via single-use `settled` flag + `cleanup()`.

**`continue`** (L1151–1204, `public async`)  
Sets state to RUNNING before sending DAP `continue`. Reverts to PAUSED on error. Returns `DebugResult`.

**`pause`** (L1206–1355, `public async`)  
If `threadId` not provided or is 0, discovers first available thread via DAP `threads` request. Registers `stopped` listener **before** sending pause. After response, if state is already PAUSED and no stop event seen, settles immediately. If no `stopped` event within `pauseGraceMs`, returns `pending: true`. Returns `DebugResult`.

**`listThreads`** (L1357–1375, `public async`)  
Sends DAP `threads` request; propagates failure if `response.success === false` (rather than returning empty list).

**`evaluateExpression`** (L1435–1626, `public async`)  
Validates expression, resolves frame ID from stack trace if not provided, sends DAP `evaluate` with policy-specified context (default `'variables'`). Supports `timeoutMs` override via `resolveDapTimeoutOverride`. Maps common error substrings (SyntaxError, NameError, TypeError, frame) to user-friendly messages.

**`attachToProcess`** (L1631–1904, `public async`)  
Attach workflow: validates `verifyTimeout`, calls `startProxyManager` with `request: 'attach'`, performs handshake. If `stopOnEntry !== false`, polls DAP `threads` until at least one thread is found (up to `attachVerifyTimeoutMs` or `verifyTimeout` override), tears down proxy on failure. Handles `pauseAfterAttach` policy: sends explicit pause and waits for `stopped` event.

**`detachFromProcess`** (L1936–1998, `public async`)  
Sends DAP `disconnect` with `terminateDebuggee: false`, then stops proxy. If `terminateProcess=true`, delegates to `closeSession`.

**`redefineClasses`** (L2000–2056, `public async`)  
Sends custom DAP `redefineClasses` request (Java hot-swap). Supports optional `timeoutMs` override.

---

### Private Helpers

- **`waitForDryRunCompletion`** (L353–409): `Promise.race` between `dry-run-complete` event and timeout. Checks `hasDryRunCompleted()` synchronously first.
- **`truncateForLog`** (L1380–1383): Truncates strings for log output.
- **`resolveDapTimeoutOverride`** (L1393–1412): Validates and clamps caller-supplied DAP timeout (max 600000ms).
- **`withTimeoutHint`** (L1415–1421): Appends timeout hint message to timeout-related error strings.
- **`sendThreadsRequestBounded`** (L1911–1931): `Promise.race` between DAP `threads` request and a deadline rejection, used during attach verification.
- **`MAX_DAP_TIMEOUT_MS`** (L1386): Static constant = 600000ms.

---

### Architectural Patterns

- **Abstract base class mixin**: Intended to be combined with `SessionManagerData` (state, stores, registries) and a concrete class for full session management.
- **Event-driven step/pause**: Step and pause operations register listeners on `proxyManager` before sending the DAP request to avoid race conditions where events arrive before await resumes.
- **Grace window pattern**: Step and pause both settle with `pending: true` instead of timing out hard, allowing the stopped event to still be processed asynchronously by core listeners.
- **DAP `setBreakpoints` replace-all semantics**: On every `setBreakpoint` call, all breakpoints for the same file are sent together.
- **Attach verification**: After attach handshake, polls `threads` endpoint to confirm a real debuggable target before reporting success (prevents false PAUSED state).
- **Dry-run path**: Calls proxy start but waits for `dry-run-complete` event instead of debug readiness events; returns spawn command/script without actual debugging.
- **Toolchain validation**: If adapter reports incompatible MSVC toolchain, session is reverted to `CREATED` (not `ERROR`) and `canContinue` is set in the result, allowing caller to warn but proceed.

---

### Key Dependencies

- `SessionManagerData` (parent): provides `logger`, `sessionStore`, `adapterRegistry`, `proxyManagerFactory`, `selectPolicy`, `_getSessionById`, `_updateSessionState`, `closeSession`, `setupProxyEventHandlers`, `cleanupProxyEventHandlers`, `getStackTrace`, `findFreePort`, `fileSystem`, `logDirBase`, `defaultDapLaunchArgs`, `dryRunTimeoutMs`
- `@debugmcp/shared`: `SessionState`, `SessionLifecycleState`, `Breakpoint`, `AdapterConfig`, `sanitizePayloadForLogging`
- `./session-store.js`: `ManagedSession`, `ToolchainValidationState`
- `../proxy/proxy-config.js`: `ProxyConfig`
- `../errors/debug-errors.js`: `SessionTerminatedError`, `ProxyNotRunningError`, `DebugSessionCreationError`, `PythonNotFoundError`
- `../utils/error-messages.js`: `ErrorMessages`
