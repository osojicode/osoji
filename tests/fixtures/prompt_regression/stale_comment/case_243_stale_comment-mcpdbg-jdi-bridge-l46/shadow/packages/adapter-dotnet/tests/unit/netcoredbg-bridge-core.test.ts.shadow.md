# packages\adapter-dotnet\tests\unit\netcoredbg-bridge-core.test.ts
@source-hash: 6f3db79240499447
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:44Z

## Unit Tests for `netcoredbg-bridge-core`

Tests for the TCP bridge between IDE clients and the `netcoredbg` debugger process. All tests use mock spawn functions and real (loopback) TCP connections — no actual `netcoredbg` binary is invoked.

### Test Suite: `netcoredbg-bridge-core` (L56–213)

Tests `createBridge` from `../../src/utils/netcoredbg-bridge-core.js`, verifying:

1. **TCP server creation** (L76–82): Bridge starts a TCP server on OS-assigned port when `0` is passed.
2. **Spawn on first connection** (L84–99): `netcoredbg` is spawned with `['--interpreter=vscode']` and `stdio: ['pipe','pipe','pipe']` on first client connect.
3. **TCP → stdin forwarding** (L101–115): Data written to the TCP socket is forwarded verbatim to the child process `stdin.write`.
4. **stdout → TCP forwarding** (L117–133): Data emitted from mock `stdout` is received by the connected TCP client.
5. **Single-client enforcement** (L135–152): A second TCP connection is immediately destroyed; only one spawn occurs.
6. **Cleanup on socket close** (L154–165): When the client socket closes, `cp.kill()` is called.
7. **Cleanup on process exit** (L167–181): When the child process emits `'exit'`, the TCP socket is ended/closed.
8. **Spawn error handling** (L183–198): A child process `'error'` event causes socket close and logs `"netcoredbg error: ENOENT"` to the stderr stream.
9. **stderr forwarding** (L200–212): Data from `mockCp.stderr` is forwarded to the configured `stderrStream`.

### Helpers

- **`createMockChildProcess()`** (L16–27): Constructs a minimal fake `ChildProcess` using `PassThrough` for stdin and `EventEmitter` for stdout/stderr. Exposes `kill` (vi.fn) and `pid = 12345`.
- **`waitForListening(server)`** (L30–39): Promise resolving to the OS-assigned port once the `net.Server` is listening.
- **`connectClient(port)`** (L42–47): Creates a real `net.Socket` connection to `127.0.0.1:{port}`.
- **`tick()`** (L50): 30ms setTimeout promise used to flush async event handlers between steps.

### Test Fixture Setup (L63–74)

Each test creates a fresh `mockCp`, a spy `spawnFn`, a `stderrChunks` collector array, and a minimal `stderrStream` stub (`{ write }` duck-type). `afterEach` calls `bridge?.cleanup()`.

### Key Contract Under Test (`createBridge` signature observed)
```
createBridge(executablePath: string, port: number, options: { spawnFn, stderr })
```
Returns a `BridgeHandle` with at least `{ server: net.Server, cleanup: () => void }`.

### Notable Patterns
- Uses vitest mocking (`vi.fn`, `vi.spyOn`) rather than jest.
- Real TCP loopback sockets are used (not mocked), so port 0 is passed to get OS-assigned ephemeral ports.
- `PassThrough` stream required via `require('stream')` (CommonJS-style, L17) despite ESM context.
- `mockCp.stdout` / `mockCp.stderr` are bare `EventEmitter`s — the bridge must only call `.on('data', ...)` on them (not `.pipe()` or stream methods).