# src\utils\error-messages.ts
@source-hash: 27887c6bd3d932d9
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:14Z

## Purpose
Centralized registry of error/informational message factory functions for timeout and async-operation feedback in the debug server. Ensures consistent wording between implementation and tests.

## Key Export

### `ErrorMessages` (L6–97)
A plain object (not a class) whose properties are arrow functions returning formatted strings. All functions are pure — no side effects or external dependencies.

| Property | Signature | Line | Description |
|---|---|---|---|
| `dapRequestTimeout` | `(command: string, timeout: number) => string` | L15 | DAP request timed out; includes restart guidance. Default context: 35s timeout. |
| `dapRequestTimeoutHint` | `() => string` | L27 | Supplementary hint for operations accepting a per-request `timeout` ms argument (e.g. `evaluate_expression`, `redefine_classes`). Notes that the debuggee may still be running. |
| `proxyInitTimeout` | `(timeout: number) => string` | L38 | Debug proxy failed to initialize within timeout. Default context: 30s. |
| `stepStillRunning` | `(graceSeconds: number) => string` | L51 | Informational: step dispatched but `stopped` event not yet received after grace window. Suggests checking session state or calling `pause_execution`. |
| `pausePending` | `(graceSeconds: number) => string` | L65 | Informational: pause acknowledged but no `stopped` event within grace window. Suggests checking session state. |
| `attachVerifyFailed` | `(timeoutMs: number, lastFailure: string) => string` | L81 | Attach handshake succeeded but no threads reported within verification window. References `verifyTimeout` parameter on `attach_to_process`. |
| `adapterReadyTimeout` | `(timeout: number) => string` | L93 | Waiting for adapter ready/configured state timed out. Default context: 30s. |

## Consumers (per inline JSDoc)
- `dapRequestTimeout` → `src/proxy/proxy-manager.ts`
- `dapRequestTimeoutHint` → `src/session/session-manager-operations.ts`
- `proxyInitTimeout` → `src/proxy/proxy-manager.ts`
- `stepStillRunning` → `src/session/session-manager-operations.ts`
- `pausePending` → `src/session/session-manager-operations.ts`
- `attachVerifyFailed` → `src/session/session-manager-operations.ts`
- `adapterReadyTimeout` → `src/session/session-manager.ts` (as warning log)

## Architectural Notes
- No imports; fully self-contained utility module.
- All message factories are deterministic, making them straightforward to assert in tests.
- Timeout values are passed as parameters — this file does not define default constants; callers supply actual values.