# scripts\test-ipc.js
@source-hash: 0aacfd28ee6ca516
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:24Z

## Purpose
A manual diagnostic script that verifies IPC (Inter-Process Communication) between a parent Node.js process and the compiled `proxy-bootstrap.js` child process. Used to validate that `child_process.spawn` with `stdio: ['pipe', 'pipe', 'pipe', 'ipc']` correctly enables `.send()` / `message` communication.

## Execution Flow
1. **L11-16**: Spawns `dist/proxy/proxy-bootstrap.js` via `process.execPath` with an IPC channel as fd 3. The child's CWD is set to the project root (`..` relative to `scripts/`).
2. **L18-40**: On `spawn` event, logs the child PID and IPC readiness. After a 1-second delay (L24-39), sends a hardcoded `init` command message to the child.
3. **L42-44**: Logs any IPC messages received back from the child.
4. **L46-48**: Forwards child stderr to parent stdout with a `[Child stderr]` prefix.
5. **L50-52**: Forwards child stdout to parent stdout with a `[Child stdout]` prefix.
6. **L54-56**: Logs child exit code.
7. **L59-62**: Hard kills the child after 10 seconds as a safety teardown.

## Test Message Schema (L26-34)
The `init` message sent to the proxy child includes:
- `cmd: 'init'` — command discriminant
- `sessionId: 'test-session'`
- `executablePath: 'node'`
- `adapterHost: 'localhost'`
- `adapterPort: 12345`
- `logDir: '.'`
- `scriptPath: 'test.js'`

## Key Details
- **`__dirname` polyfill (L6)**: ESM-compatible `__dirname` derived from `import.meta.url`.
- **Target binary (L12)**: `dist/proxy/proxy-bootstrap.js` — requires a prior build step; this script will fail if the dist output is absent.
- **IPC channel (L14)**: `stdio` index 3 is the IPC fd; indices 0-2 are piped for stdin/stdout/stderr capture.
- **No assertions or pass/fail logic**: Output is purely observational — human-reviewed via console logs.
- **Timeout values**: 1 s init wait (L39), 10 s kill timeout (L62).