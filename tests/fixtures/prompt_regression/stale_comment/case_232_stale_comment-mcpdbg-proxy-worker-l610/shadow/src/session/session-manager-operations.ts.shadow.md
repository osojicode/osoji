# src\session\session-manager-operations.ts
@source-hash: 5dc0d9d7c3837b52
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:35:33Z

## SessionManagerOperations (L62-2057)

Abstract class providing debug operation methods for session management. Extends `SessionManagerData` (from `session-manager-data.js`), forming a mixin chain toward the concrete `SessionManager`. Consumers call these methods via the concrete subclass. All methods operate on `ManagedSession` objects retrieved from `sessionStore`.

### Purpose
Implements the DAP-facing debug operations: starting/attaching debug sessions, stepping (over/into/out), continue, pause, breakpoint management, expression evaluation, thread listing, class redefinition, and process detach. Orchestrates adapter selection, proxy lifecycle, and event-driven readiness waiting.

---

### Key Interfaces

**`EvaluateResult` (L36-45)**
Return type for `evaluateExpression`. Fields: `success`, `result`, `type`, `variablesReference`, `namedVariables`, `indexedVariables`, `presentationHint`, `error`.

**`RedefineClassesResult` (L47-57)**
Return type for `redefineClasses`. Fields: `success`, `redefined`, `redefinedCount`, `skippedNotLoaded`, `failedCount`, `failed`, `scannedFiles`, `newestTimestamp`, `error`.

---

### Protected Timing Constants (overridable by tests)

| Field | Default | Purpose |
|---|---|---|
| `attachVerifyTimeoutMs` (L72) | 5000ms | Max wait for threads after attach handshake |
| `attachVerifyIntervalMs` (L73) | 250ms | Poll interval for attach thread discovery |
| `attachPauseStopTimeoutMs` (L80) | 5000ms | Max wait for 'stopped' event after post-attach pause |
| `stepGraceMs` (L90) | 5000ms | Grace window for step operations before returning pending |
| `pauseGraceMs` (L91) | 5000ms | Grace window for pause operations before returning pending |

---

### Key Methods

**`startProxyManager` (L93-348)** — Protected. Core orchestration: creates session log directory, resolves adapter port, builds launch/attach config, creates adapter via `adapterRegistry.create`, transforms config via `adapter.transformLaunchConfig` or `adapter.transformAttachConfig`, resolves executable path, builds adapter command, constructs `ProxyConfig`, creates `ProxyManager` via factory, attaches event handlers, and starts the proxy. Returns `LanguageSpecificLaunchConfig`.

- Detects attach mode via `launchArgs.request === 'attach'` or `launchArgs.__attachMode === true` (L145-146).
- For non-attach mode, sets `program`, `args`, `cwd` only if not already present (L153-167).
- Handles toolchain validation (MSVC detection) at L209-228.
- Throws `PythonNotFoundError` for Python executable failures, `DebugSessionCreationError` for others (L243-251).
- Uses `adapter.usesDirectConnectForAttach?.()` to skip building adapter command for direct-connect attach (L259-262).
- Uses `policy.getInitializationBehavior?.()` for `stopOnEntry` default override (L273-279).

**`startDebugging` (L411-798)** — Public. Full session start flow. Handles dry-run branch (L443-527) separately: starts proxy, waits up to `dryRunTimeoutMs` for `dry-run-complete` event, returns snapshot. For normal flow: starts proxy, calls `policy.performHandshake`, waits for readiness (stopped/adapter-configured/terminated/exited/exit events or 30s timeout at L657-664). On error: reads proxy log tail (last 80 lines), captures toolchain validation state, distinguishes MSVC toolchain errors from general errors.

**`setBreakpoint` (L801-901)** — Public. Adds breakpoint to session store, then sends DAP `setBreakpoints` (replace-all for the file) if proxy is active. Updates `verified`, `line`, `message` from response. Adds .NET PDB format hint when `no symbols` message detected (L868-871).

**`stepOver` (L903-943)**, **`stepInto` (L945-985)**, **`stepOut` (L987-1027)** — Public. Each validates PAUSED state and thread ID, then delegates to `_executeStepOperation` with DAP command `next`/`stepIn`/`stepOut`.

**`_executeStepOperation` (L1029-1149)** — Private. Sends DAP step command, listens for `stopped`/`terminated`/`exited`/`exit` events. On `stopped`, fetches stack trace to capture location. Grace timeout returns `{ pending: true }` result. Uses idempotent `settle()` guard.

**`continue` (L1151-1204)** — Public. Sends DAP `continue`. Sets state to RUNNING _before_ sending DAP request; reverts to PAUSED on error.

**`pause` (L1206-1355)** — Public. Discovers threadId via `threads` request if not provided (L1234-1245). Registers `stopped`/`terminated`/`exited`/`exit` listeners _before_ sending DAP `pause`. Waits for `stopped` event with `pauseGraceMs` grace window; captures location from stack trace on stop. Guard for state-already-PAUSED race after DAP response (L1339-1341).

**`listThreads` (L1357-1375)** — Public. Sends DAP `threads`, propagates failures (doesn't return empty list on error).

**`evaluateExpression` (L1435-1626)** — Public. Validates PAUSED state, resolves frameId from stack trace if not provided, sends DAP `evaluate` with policy-determined context (via `policy.getEvaluateContext?.()`). Supports per-request timeout override. Classifies errors (SyntaxError/NameError/TypeError/frame). Returns `EvaluateResult`.

**`attachToProcess` (L1631-1904)** — Public. Validates `verifyTimeout` (max 600000ms). Starts proxy in attach mode with `request: 'attach'` + `__attachMode: true`. Calls `policy.performHandshake`. Polls DAP `threads` until deadline (`sendThreadsRequestBounded`) to verify attach. If no threads found: tears down proxy, throws. Selects thread (prefers "main"), calls `proxyManager.setCurrentThreadId`. If `policy.getAttachBehavior?.().pauseAfterAttach`: sends DAP `pause`, waits for `stopped` with `attachPauseStopTimeoutMs`. Sets PAUSED or RUNNING state based on `stopOnEntry`.

**`detachFromProcess` (L1936-1998)** — Public. If `terminateProcess`: delegates to `closeSession`. Otherwise sends DAP `disconnect` with `terminateDebuggee: false`, stops proxy, sets STOPPED + TERMINATED lifecycle.

**`redefineClasses` (L2000-2056)** — Public. Sends custom DAP `redefineClasses` request (Java hot-swap). Supports timeout override.

---

### Private Helpers

- **`waitForDryRunCompletion` (L353-409)** — Races `dry-run-complete` event against timeout; cleans up listener in `finally`.
- **`truncateForLog` (L1380-1383)** — Truncates strings to `maxLength` (default 1000) for log safety.
- **`MAX_DAP_TIMEOUT_MS` (L1386)** — Static constant: 600000ms (10 min) ceiling for caller timeout overrides.
- **`resolveDapTimeoutOverride` (L1393-1412)** — Validates and clamps caller-supplied timeout; returns `{ error }` or `{ timeoutMs }`.
- **`withTimeoutHint` (L1415-1421)** — Appends timeout hint from `ErrorMessages.dapRequestTimeoutHint()` to timeout-related errors.
- **`sendThreadsRequestBounded` (L1911-1931)** — Races DAP `threads` request against a timer; used during attach verification.

---

### Architectural Patterns

- **Mixin chain**: `SessionManagerOperations extends SessionManagerData` — all infrastructure (logger, sessionStore, adapterRegistry, proxyManagerFactory, fileSystem, selectPolicy, etc.) is inherited from parent classes.
- **Event-driven readiness**: All async operations (start, step, pause, attach) use `Promise` + event listener patterns with `cleanup()` and idempotent `settle()` guards.
- **Grace windows**: Step/pause operations return `pending: true` (not error) when the debuggee doesn't respond within the grace window, preserving async completion via `handleStopped` in the core.
- **Attach verification**: Thread polling loop prevents false-positive "paused" reports for adapters whose child sessions connect asynchronously.
- **Policy dispatch**: `selectPolicy(session.language)` used throughout to get language-specific behavior (handshake, evaluate context, stopOnEntry default, attach behavior, session readiness).
- **DAP setBreakpoints is replace-all**: `setBreakpoint` always sends all breakpoints for the file, not just the new one.
