# tests\core\unit\session\session-manager-workflow.test.ts
@source-hash: e52ffab525c14c23
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:51Z

## Purpose
Unit tests for `SessionManager` covering complete debug session lifecycle workflows, including startup event handling, dry runs, and breakpoint/step operations.

## Test Structure
- **Single `describe` block**: `SessionManager - Debug Session Workflow` (L9–240)
- **Nested `describe`**: `Complete Debug Cycle` (L34–240) — 6 `it` tests

## Setup / Teardown
- `beforeEach` (L14–26): Enables fake timers (`shouldAdvanceTime: true`), creates mock dependencies via `createMockDependencies()`, instantiates `SessionManager` with config pointing to `/tmp/test-sessions` and DAP defaults `{ stopOnEntry: true, justMyCode: true }`.
- `afterEach` (L28–32): Restores real timers, clears all mocks, resets `mockProxyManager`.

## Test Cases

### 1. Full Debug Workflow (L35–83)
Creates a session → starts debugging with `stopOnEntry: true` → verifies `PAUSED` state → sets a breakpoint on `test.py:15` (checks `setBreakpoints` DAP command) → steps over with a pre-emitted `stopped` event → closes session and confirms removal from manager.

### 2. Dry Run Workflow (L85–114)
Creates session → calls `startDebugging` with `dryRun=true` → expects `result.data.dryRun === true`, state `STOPPED`, no "proxy exited before initialization" error logs, and `mockProxyManager.startCalls[0].dryRunSpawn === true`.

### 3. `stopOnEntry=false` Workflow (L116–147)
Creates session → registers a one-time `start` listener on `mockProxyManager` that, when `stopOnEntry` is falsy, emits `adapter-configured` after 10 ms instead of a `stopped` event → expects state `RUNNING` and `startCalls[0].stopOnEntry === false`.

### 4. `terminated` Event During Startup (L149–179)
Overrides `mockProxyManager.start` to emit `'terminated'` on `process.nextTick` → expects `result.success === true`, an info log containing `'terminated during startup'`, and `stopCalls === 1` (proxy reap, issue #122).

### 5. `exited` Event During Startup (L181–210)
Same pattern as above but emits `'exited'` with exit code `0` → expects info log `'exited during startup'` and `stopCalls === 1`.

### 6. `exit` Event During Startup (L212–239)
Emits `'exit'` with code `1` and signal `'SIGKILL'` → expects info log `'proxy exited during startup'` (note: does **not** assert `stopCalls`).

## Key Dependencies
- `SessionManager` / `SessionManagerConfig` from `src/session/session-manager.js`
- `DebugLanguage`, `SessionState` from `@debugmcp/shared`
- `createMockDependencies` from `./session-manager-test-utils.js` — provides `mockProxyManager`, `mockLogger`, and related mock infrastructure

## Notable Patterns
- `vi.runAllTimersAsync()` is used to flush async timers after calling `startDebugging`, allowing proxy event simulation before awaiting the promise.
- Proxy startup events (`terminated`, `exited`, `exit`) are injected via `process.nextTick` after overriding `mockProxyManager.start` with `vi.fn()`.
- Issue #122 is referenced in two tests (L177, L208) noting that natural termination must call `stop()` to reap the proxy process.
- The `exit` test (L212–239) does **not** assert `stopCalls`, which may be an intentional omission or an oversight compared to the other two termination tests.
