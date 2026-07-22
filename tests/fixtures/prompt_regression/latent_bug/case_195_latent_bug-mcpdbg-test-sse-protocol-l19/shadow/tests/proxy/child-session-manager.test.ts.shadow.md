# tests\proxy\child-session-manager.test.ts
@source-hash: d8db8958821a7380
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:41Z

## Purpose
Test suite for `ChildSessionManager` — validates child session lifecycle management, policy-based routing/mirroring, deduplication, event forwarding, and shutdown behavior across JavaScript (multi-session), Python (single-session), and Default adapter policies.

## Test Structure

### Mock Infrastructure
- **`MockMinimalDapClient`** (L12–51): `EventEmitter` subclass standing in for the real `MinimalDapClient`. Tracks `connected` state, records all `sendRequest` calls in `requests[]`. On `initialize` command, emits a delayed `initialized` event via `setTimeout(..., 10)`. On `threads` returns one thread. Provides `connect()`, `shutdown()`, and `disconnect()` methods.
- **`vi.mock` for `minimal-dap.js`** (L54–56): Replaces `MinimalDapClient` with `MockMinimalDapClient` to avoid circular dependencies and real network I/O.

### Describe Blocks

#### `JavaScript policy (multi-session)` (L61–279)
Manager created with `JsDebugAdapterPolicy`, `host: 'localhost'`, `port: 9229`.

- **L70–100**: `createChildSession` with launch-mode parent — uses `vi.useFakeTimers()` and advances 20 s past two internal waits (15 s `ensureChildStopped` + 3 s post-attach `initialized`). Asserts `childCreated` event fires with `(pendingId, childObj)` and `getActiveChild()` / `hasActiveChildren()` become truthy.

- **L102–134**: Attach-mode parent skips `ensureChildStopped` — only 4 s of fake time needed (only the 3 s post-attach wait remains). Asserts no `pause` command in `child.requests`.

- **L136–146**: `shouldRouteToChild` — JS policy routes `threads`, `pause`, `continue`, `stackTrace`; does NOT route `initialize` or `launch`.

- **L148–161**: `storeBreakpoints` stores data internally for JS policy — confirms `storedBreakpoints.size > 0`.

- **L163–184**: Breakpoint mirroring — after a child is created, `storeBreakpoints` triggers a `setBreakpoints` command forwarded to the child's `requests[]`.

- **L187–219**: Concurrent adoption guard — two `createChildSession` calls in flight simultaneously; only one active child results.

- **L221–249**: Duplicate adoption deduplication — second `createChildSession` with same `pendingId` after first completes is a no-op; `childSessions.size` remains 1.

- **L252–278**: Child event forwarding — after child is adopted, events emitted on the child object are re-emitted by the manager as `childEvent`.

#### `Python policy (single-session)` (L281–306)
Manager with `PythonAdapterPolicy`, `port: 5678`.
- `shouldRouteToChild` returns `false` for all commands (L290–294).
- `storeBreakpoints` does NOT populate `storedBreakpoints` (size stays 0) (L296–305).

#### `Default policy` (L308–322)
- `hasActiveChildren()` → false, `getActiveChild()` → null, `shouldRouteToChild('any-command')` → false.

#### `Shutdown` (L324–354)
- Creates one child session, confirms it's active, calls `manager.shutdown()`, verifies `hasActiveChildren()` → false and `getActiveChild()` → null.

## Key Patterns
- **Fake timers pattern**: Every async `createChildSession` test wraps with `vi.useFakeTimers()` / `vi.useRealTimers()` in try/finally and calls `await vi.advanceTimersByTimeAsync(N)` before awaiting the promise, because the real implementation has internal timeouts (15 s + 3 s).
- **Internal field access**: Tests reach into `(manager as any).childSessions` (L245) and `(manager as any).storedBreakpoints` (L149, 160, 304) to assert internal state.
- **Policy dispatch tested externally**: `shouldRouteToChild` and `storeBreakpoints` behavior differs by policy without needing to inspect internals of policy objects.

## Dependencies
- `ChildSessionManager` from `src/proxy/child-session-manager.ts`
- `JsDebugAdapterPolicy`, `PythonAdapterPolicy`, `DefaultAdapterPolicy`, `AdapterPolicy` from `@debugmcp/shared`
- `MinimalDapClient` from `src/proxy/minimal-dap.ts` (mocked)
- `DebugProtocol` from `@vscode/debugprotocol` (type only)
- `vitest` test framework with fake timers

## Critical Constraints
- Attach-mode parent config (`request: 'attach'`) must bypass the 15 s `ensureChildStopped` wait — only 4 s needed to resolve.
- Same `pendingId` on second call must be idempotent (deduplication via `isAdopted()`).
- `shutdown()` must disconnect all child sessions and clear internal state.
