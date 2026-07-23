# tests\test-utils\mocks\child-process.ts
@source-hash: 32801a2ff1e5bf75
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:19Z

## Overview
Test utility providing mock implementations for Node.js `child_process` module functions (`spawn`, `exec`, `execSync`, `fork`). Designed for use with Vitest's `vi.mock()` system. Exports a singleton `ChildProcessMock` instance, destructured mock functions, and a `MockChildProcess` class for fine-grained process simulation.

---

## Key Classes

### `MockChildProcess` (L14–89) — `public`
Extends `EventEmitter`. Simulates a spawned child process with IPC support.

**Fields:**
- `stdin: null` (L16) — always null; not simulated
- `stdout: EventEmitter` (L17) — readable stream substitute
- `stderr: EventEmitter` (L18) — readable stream substitute
- `kill: vi.fn()` (L21) — sets `this.killed = true` on call (L36–39)
- `send: vi.fn()` (L22–25) — returns `true` by default
- `pid: number` (L28) — random 0–9999 if not provided
- `killed: boolean = false` (L29)

**Simulation helpers:**
- `simulateExit(code, signal)` (L45–48) — emits `'exit'` then `'close'`
- `simulateError(error)` (L53–55) — emits `'error'`
- `simulateStdout(data)` (L60–62) — emits `Buffer.from(data)` on `stdout`
- `simulateStderr(data)` (L67–69) — emits `Buffer.from(data)` on `stderr`
- `simulateMessage(message)` (L74–76) — emits `'message'` (IPC)
- `reset()` (L81–88) — removes all listeners from self, stdout, stderr; clears mock state; resets `killed`

---

### `ChildProcessMock` (L91–344) — `internal` (not exported directly)
Manages a collection of `MockChildProcess` instances and provides vi.fn()-based implementations for `spawn`, `exec`, `execSync`, `fork`.

**Constructor:** calls `setupMocks()` at L102.

**Public methods:**
- `reset()` (L108–121) — resets all four vi.fn() mocks, resets all tracked processes, clears `mockProcesses`, re-runs `setupMocks()`
- `createMockProcess()` (L189–193) — creates and tracks a standalone `MockChildProcess`
- `getAllMockProcesses()` (L198–200) — returns shallow copy of `mockProcesses`
- `setupPythonSpawnMock(options)` (L207–249) — overrides `spawn` to emit sequenced stdout/stderr messages then exit; options: `exitCode` (default 0), `exitDelay` (default 100ms), `stdout[]`, `stderr[]`
- `setupPythonVersionCheckMock(pythonVersion)` (L254–283) — overrides `exec` to return `"Python {version}"` when command contains `python` and `--version`
- `setupProxySpawnMock(options)` (L288–343) — overrides `spawn` to simulate an IPC-based proxy process; intercepts JSON `{cmd: 'init'}` messages and responds with `{type: 'status', status: 'adapter_configured_and_launched'}` or `{type: 'error'}`; returns `{ get: () => MockChildProcess | null }` accessor

**Private method:**
- `setupMocks()` (L126–184) — installs default vi.fn() implementations:
  - `spawn`: creates `MockChildProcess`, schedules `simulateExit(0)` after 50ms
  - `exec`: handles optional options arg, invokes callback with `('mock stdout output', '')` after 10ms, returns `MockChildProcess`
  - `execSync`: returns `Buffer.from('mock stdout output')`
  - `fork`: same as `spawn` but accepts `modulePath`

---

## Module-Level Exports

| Export | Type | Line | Description |
|---|---|---|---|
| `MockChildProcess` | class | 14 | Named export — extend/instantiate directly in tests |
| `childProcessMock` | singleton | 347 | Primary handle for test control; exposes all setup helpers |
| `spawn` | vi.fn() | 351 | Destructured from singleton; usable as direct module mock |
| `exec` | vi.fn() | 352 | Destructured from singleton |
| `execSync` | vi.fn() | 353 | Destructured from singleton |
| `fork` | vi.fn() | 354 | Destructured from singleton |
| `default` | object | 358–365 | `{ spawn, exec, execSync, fork, __childProcessMock }` — intended for `vi.mock('child_process', () => default)` usage |

---

## Usage Patterns

**Basic module mock:**
```ts
vi.mock('child_process', () => import('./mocks/child-process'));
```
The default export shape mirrors the `child_process` module API.

**Accessing the spawned process in a test:**
```ts
const handle = childProcessMock.setupProxySpawnMock({ respondToInit: true });
// ... trigger code under test ...
const proc = handle.get(); // MockChildProcess
```

**Python version check testing:**
```ts
childProcessMock.setupPythonVersionCheckMock('3.11.2');
// exec callback will receive 'Python 3.11.2' for commands with `python --version`
```

---

## Notable Design Decisions
- `@ts-nocheck` (L1) suppresses TypeScript errors throughout — EventEmitter is cast `as any` to satisfy stream type constraints
- `stdout`/`stderr` are plain `EventEmitter` instances (L17–18), not proper `Readable` streams — only `emit('data', ...)` and listener management are supported
- `stdin` is always `null` (L16); no stdin simulation provided
- `setupProxySpawnMock` overrides `send` on the mock process (L307) to intercept outbound IPC, simulating bidirectional communication
- All `setTimeout` delays are small (10–100ms) for test speed; fake timers may need `vi.useFakeTimers()` in consuming tests
- `reset()` on `ChildProcessMock` calls `setupMocks()` again (L120), restoring default implementations — calling tests should invoke `childProcessMock.reset()` in `afterEach`