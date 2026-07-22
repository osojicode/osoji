# tests\unit\dap-core\handlers.test.ts
@source-hash: 16a7b06ee6b265ff
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## Unit Tests: DAP Core Message Handlers

Tests for the DAP (Debug Adapter Protocol) core message handling logic imported from `src/dap-core/index.js`. Validates the pure functional message dispatch system (`handleProxyMessage`) and message validation utility (`isValidProxyMessage`).

### Test Structure

**Top-level describe:** `DAP Core Handlers` (L15)
- All tests share a `DAPSessionState` created via `createInitialState('test-session-123')` in `beforeEach` (L19–21)

---

### `handleProxyMessage` Test Groups

#### Session Validation (L23–41)
- Rejects messages with `sessionId` mismatching the session's own ID
- Expects a single `log` command with level `'warn'` and message `'Session ID mismatch. Expected test-session-123, got wrong-session'`
- `result.newState` is `undefined` on rejection

#### Status Messages — Phase 1 (L43–185)

| Status | Expected commands | State changes |
|---|---|---|
| `proxy_minimal_ran_ipc_test` (L44–64) | `log(info)` + `killProcess` | none |
| `dry_run_complete` (L66–88) | `log(info)` + `emitEvent('dry-run-complete', [command, script])` | none |
| `adapter_configured_and_launched` (not initialized, L90–119) | `log(info)` + `emitEvent('adapter-configured')` + `emitEvent('initialized')` | `initialized=true`, `adapterConfigured=true` |
| `adapter_configured_and_launched` (already initialized, L121–136) | only 2 commands; no `initialized` event re-emitted | — |
| `adapter_exited`, `dap_connection_closed`, `terminated` (L138–168) | `log(info, "Status: <status>")` + `emitEvent('exit', [code, signal])` | none |
| `adapter_exited` with missing code (L170–184) | `emitEvent('exit', [1, undefined])` — default code is `1` | none |

#### Error Messages — Phase 1 (L187–210)
- `ProxyErrorMessage` type produces: `log(error, '[ProxyManager] Proxy error: <msg>')` + `emitEvent('error', [new Error(msg)])`

#### DAP Events — Phase 2 (L212–326)

| DAP event | Expected `emitEvent` args | State change |
|---|---|---|
| `stopped` with `threadId` (L213–238) | `['stopped', threadId, reason, body]` | `currentThreadId = 42` |
| `stopped` without `threadId` (L240–258) | `['stopped', undefined, reason, body]` | no state change (`result.newState === state`) |
| `continued` (L260–275) | `['continued', []]` | — |
| `terminated` (L277–291) | `['terminated', []]` | — |
| `exited` (L293–308) | `['exited', []]` | — |
| unknown/custom event `'custom'` (L310–325) | `emitEvent('dap-event', ['custom', body])` | — |

All DAP event tests also expect a `log(info, '[ProxyManager] DAP event: <event>', data: body)` as `commands[0]`.

#### Unknown Message Types (L328–346)
- Messages with unrecognized `type` produce single `log(warn, 'Unknown message type', data: message)`

---

### `isValidProxyMessage` Tests (L349–381)

**Valid messages** (L351–356): Objects with `{type: string, sessionId: string}` plus type-specific required fields:
- `status` + `status` field
- `error` + `message` field
- `dapEvent` + `event` field
- `dapResponse` + `requestId` field

**Invalid messages** (L363–379): `null`, `undefined`, primitives, arrays, `{}`, objects missing `sessionId`, missing `type`, wrong-typed `type` (number), wrong-typed `sessionId` (number)

---

### Key Contracts Verified
- Commands array is the primary output; `newState` is `undefined` when no state change, or a partial state update object
- Session ID mismatch always short-circuits with a single warn log and `newState: undefined`
- `adapter_configured_and_launched` only emits `initialized` event when `state.initialized` is `false`
- Exit events default `code` to `1` when absent from message
- Unknown DAP events are forwarded via generic `'dap-event'` channel
