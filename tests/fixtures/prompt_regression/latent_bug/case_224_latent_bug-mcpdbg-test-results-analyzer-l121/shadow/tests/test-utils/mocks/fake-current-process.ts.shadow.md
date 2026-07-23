# tests\test-utils\mocks\fake-current-process.ts
@source-hash: 7215db7b8c2799ae
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:50Z

## Purpose
Test utility providing a fake implementation of `ProcessLike` (the current process handle) for unit tests. Backed by `EventEmitter` so production code's `proc.on(...)` binds to this object — tests drive lifecycle events via `fakeProc.emit(...)` without leaking into the vitest worker (issue #159). Distinct from `FakeProcess` in `tests/implementations/test/fake-process-launcher.ts`, which models a spawned child process (`IProcess`).

## Key Class: `FakeCurrentProcess` (L16–78)
Extends `EventEmitter`, implements `ProcessLike`. All lifecycle events (`disconnect`, `exit`, `SIGTERM`, etc.) are test-driven via `emit()`.

### Public Fields
| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `exit` (L18) | `Mock<(code?: number) => void>` | `vi.fn()` | Recording mock; never terminates. Assert with `expect(fakeProc.exit).toHaveBeenCalledWith(n)`. |
| `send` (L24) | `Mock<(msg: unknown) => boolean> \| undefined` | `vi.fn(() => true)` | IPC send; `undefined` = no IPC channel. |
| `connected` (L26) | `boolean` | `true` | Mirrors `process.connected`. |
| `env` (L27) | `NodeJS.ProcessEnv` | `{}` | Empty env by default; tests assign as needed. |
| `argv` (L28) | `string[]` | `['/usr/bin/node', '/fake/dap-proxy-entry.js']` | Fake argv. |
| `uptime` (L29) | `Mock<() => number>` | `vi.fn(() => 0)` | Always returns 0. |
| `stdin` (L31) | `PassThrough` | new | Writable end for test input. |
| `stdout` (L32) | `PassThrough` | new | Readable end; all writes captured to `stdoutChunks`. |
| `stdoutChunks` (L35) | `readonly string[]` | `[]` | Decoded utf-8 chunks written to stdout, in order. |

### Constructor (L37–40)
Calls `super()`, then wires a `data` listener on `this.stdout` to push decoded UTF-8 strings into `stdoutChunks`.

### IPC Control Methods (L43–63)
- **`enableIPC(): this`** (L43–47) — Installs a fresh `vi.fn(() => true)` as `send`, sets `connected = true`. Chainable.
- **`disableIPC(): this`** (L50–54) — Sets `send = undefined`, `connected = false`. Chainable.
- **`failSendWith(error: Error): this`** (L57–63) — Sets `send` to a mock that throws the given error, sets `connected = false`. Models `ERR_IPC_CHANNEL_CLOSED`. Chainable.

### Inspection Helpers
- **`sentMessages` getter** (L66–68) — Returns array of first arguments passed to `send()` so far; empty array if IPC is disabled.
- **`lastListener(event: string)`** (L71–77) — Returns the most recently registered listener for `event`. Throws `Error` if none registered. Used when tests must `await` an async event handler.

## Factory Function: `createFakeCurrentProcess()` (L80–82)
Convenience factory; returns `new FakeCurrentProcess()`.

## Dependencies
- `EventEmitter` (Node `events`) — provides `on`/`emit`/`listeners` API.
- `PassThrough` (Node `stream`) — bidirectional stream for `stdin`/`stdout`.
- `vi`, `Mock` from `vitest` — mock infrastructure.
- `ProcessLike` from `../../../src/interfaces/process-interfaces.js` — production interface this class satisfies.

## Architectural Notes
- IPC state is managed as a trio: `send` (mock or `undefined`), `connected`, and `sentMessages`. Tests should use the helper methods rather than mutating fields directly.
- `stdoutChunks` provides a simple snapshot-style assertion surface for stdout output.
- All mock functions are `vi.fn()` so standard vitest matchers (`toHaveBeenCalledWith`, `toHaveBeenCalledTimes`, etc.) work directly.