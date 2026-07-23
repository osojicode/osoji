# tests\unit\dev-proxy\dev-proxy-shutdown.test.ts
@source-hash: 2d18c1f414ab9056
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:04Z

## Purpose
Unit tests for the dev-proxy shutdown wiring (`tools/dev-proxy/shutdown.mjs`), covering `installShutdownHandlers` and `killChildGracefully`. Verifies correct lifecycle: backend stop → process exit under all disconnect/signal scenarios, idempotency, timeout handling, and graceful child kill (SIGTERM/stdin-close on Windows vs SIGTERM on Unix with force-kill escalation).

## Key Imports
- `installShutdownHandlers`, `killChildGracefully` from `../../../tools/dev-proxy/shutdown.mjs` (plain JS, no types — imported with `@ts-ignore`)
- `EventEmitter` from Node `events` for fake stdin/proc/child objects
- `describe`, `it`, `expect`, `vi` from `vitest`

## Test Infrastructure

### `FakeProc` interface (L17-19)
Extends `EventEmitter` with a `vi.fn()` `exit` mock. Used as a stand-in for the Node.js `process` object.

### `makeDeps()` (L21-28)
Factory returning `{ stdin, proc, backend, log }`:
- `stdin` — `EventEmitter` simulating `process.stdin`
- `proc` — `EventEmitter` cast to `FakeProc` with `proc.exit = vi.fn()`
- `backend` — `{ stop: vi.fn().mockResolvedValue(undefined) }` (happy-path resolves)
- `log` — `vi.fn()`

### `FakeChild` interface (L158-163)
Extends `EventEmitter` with `pid: number`, `exitCode: number | null`, `kill: vi.fn()`, and `stdin: { destroyed: boolean; end: vi.fn() } | null`.

### `makeFakeChild({ withStdin })` (L165-172)
Factory for `FakeChild` with `pid=4242`, `exitCode=null`. `withStdin=false` sets `child.stdin = null`.

## Test Suites

### `installShutdownHandlers` (L30-150)
| Test | Trigger | Assertion |
|---|---|---|
| L31-43 | `stdin 'end'` | `backend.stop` called before `proc.exit(0)` |
| L45-53 | `stdin 'close'` | same as above |
| L55-63 | `stdin 'error'` (EPIPE) | treated as disconnect, exits 0 |
| L65-75 | `proc 'SIGINT'` / `'SIGTERM'` | both trigger shutdown |
| L77-93 | Multiple triggers simultaneously | idempotent: stop×1, exit×1 |
| L95-111 | `backend.stop()` hangs (never resolves) | `stopTimeoutMs:25` → still exits 0 within 2s |
| L113-122 | `backend.stop()` rejects | exits 0, logs error message |
| L124-136 | `server.onclose` chaining | wraps previous handler, calls both, triggers shutdown |
| L138-149 | Return value | returned `shutdown(reason)` fn is idempotent, logs reason |

### `killChildGracefully` (L174-269)
| Test | Scenario | Expected behavior |
|---|---|---|
| L175-185 | `null` child or `exitCode !== null` | resolves immediately, no kill |
| L187-203 | win32 + prompt exit | `child.stdin.end()` called, resolves, no force-kill |
| L205-215 | win32 + child ignores graceful | `forceKill(child.pid)` called after `killTimeoutMs` |
| L217-226 | win32 + no stdin pipe | immediate `forceKill(child.pid)` |
| L228-243 | unix + prompt exit | `child.kill('SIGTERM')`, no `stdin.end`, no force-kill |
| L245-255 | unix + grace period expires | `child.kill('SIGTERM')` then `forceKill(child.pid)` |
| L257-269 | force-kill never fires exit event | bail timer resolves after `bailMs:20` |

## Key Behavioral Contracts Verified
1. **Ordering**: `backend.stop()` must be initiated before `proc.exit()` (L39-42).
2. **Idempotency**: Any number of concurrent shutdown triggers → exactly one `stop` and one `exit`.
3. **Resilience**: Hanging or rejecting `backend.stop()` must not block `proc.exit(0)`.
4. **Server chaining**: `server.onclose` is wrapped (not replaced); previous handler is preserved and called.
5. **Platform divergence**: Windows uses stdin pipe close for graceful; Unix uses SIGTERM.
6. **Bail timer**: `killChildGracefully` has a final `bailMs` deadline independent of exit events.

## Dependencies Under Test
- `tools/dev-proxy/shutdown.mjs` — the module under test (not importable from `dev-proxy.mjs` because that runs `main()` at module top level)
