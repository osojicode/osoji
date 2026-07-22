# src\dap-core\handlers.ts
@source-hash: 72c45f1e525e0806
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:35Z

## Purpose
Pure, stateless message handler functions for the DAP (Debug Adapter Protocol) proxy layer. Translates incoming `ProxyMessage` variants into `DAPProcessingResult` objects (command lists + optional new state), following a functional/immutable state pattern. No I/O side effects — all side effects are described as `DAPCommand` objects for the caller to execute.

## Architecture
All handlers are pure functions: they accept `DAPSessionState` and a message, and return `DAPProcessingResult` (containing a `commands` array and optionally a `newState`). State mutations are performed via imported state helpers from `./state.js` and returned as `newState` — the caller is responsible for applying state and executing commands.

## Exported Functions

### `handleProxyMessage` (L25–63)
Main dispatch entry point. Validates session ID matches `state.sessionId` (L30–38), then dispatches to typed sub-handlers by `message.type`:
- `'status'` → `handleStatusMessage`
- `'error'` → `handleErrorMessage`
- `'dapEvent'` → `handleDapEvent`
- `'dapResponse'` → `handleDapResponse`
- Unknown type → returns a `log warn` command

### `isValidProxyMessage` (L259–265)
Type guard. Validates an `unknown` value is a `ProxyMessage` by checking it is a non-null object with `sessionId: string` and `type: string` fields. Used for runtime message validation before dispatching.

## Internal Handlers

### `handleStatusMessage` (L68–135)
Handles `ProxyStatusMessage` status variants:
- `'proxy_minimal_ran_ipc_test'` (L75–80): logs + emits `killProcess` command
- `'init_received'` (L82–87): logs + emits `'init-received'` event
- `'dry_run_complete'` (L89–94): logs + emits `'dry-run-complete'` event with `message.command` and `message.script`
- `'adapter_connected'` (L96–101): logs + emits `'initialized'` event; returns `newState` with `initialized = true`
- `'adapter_configured_and_launched'` (L103–118): sets `adapterConfigured = true`; also sets `initialized = true` if not already, emitting `'initialized'`; returns `newState`
- `'adapter_exited'` / `'dap_connection_closed'` / `'terminated'` (L120–131): logs + emits `'exit'` event with `message.code || 1` and `message.signal || undefined`

### `handleErrorMessage` (L140–158)
Returns log error command and emits `'error'` event with a constructed `Error` object wrapping `message.message`.

### `handleDapEvent` (L163–228)
Handles DAP events by event name:
- `'stopped'` (L179–192): extracts `threadId` and `reason` from body (L181–184); updates `currentThreadId` in state if present; emits `'stopped'` event
- `'continued'` (L194–200): emits `'continued'` event
- `'terminated'` (L202–208): emits `'terminated'` event
- `'exited'` (L210–216): emits `'exited'` event
- Default (L218–224): emits generic `'dap-event'` event with `[message.event, message.body]`

Always returns `{ commands, newState }` — `newState` defaults to unchanged `state` when no mutation needed (L176, L227).

### `handleDapResponse` (L233–254)
Looks up `message.requestId` in pending requests via `getPendingRequest` (L237). If not found, returns a debug log. If found, returns `newState` with the request removed via `removePendingRequest`. **Note:** actual Promise resolution (resolve/reject) is handled imperatively by `ProxyManager.handleDapResponse`, not here (L248–249 comment).

## Key Design Decisions
- **Immutable state pattern**: handlers never mutate `state` directly; they call pure state helpers and return the result as `newState`
- **Command pattern for side effects**: all logging, event emission, and process control are expressed as `DAPCommand` objects — no direct EventEmitter or process calls
- **Session ID guard**: every dispatched message is validated against `state.sessionId` before processing (L30–38)
- **Pending request cleanup**: `handleDapResponse` only removes the pending request from state; the caller owns Promise resolution

## Dependencies
- `./types.js`: `DAPSessionState`, `DAPProcessingResult`, `DAPCommand`, `ProxyMessage` variants
- `./state.js`: `setInitialized`, `setAdapterConfigured`, `setCurrentThreadId`, `getPendingRequest`, `removePendingRequest`
