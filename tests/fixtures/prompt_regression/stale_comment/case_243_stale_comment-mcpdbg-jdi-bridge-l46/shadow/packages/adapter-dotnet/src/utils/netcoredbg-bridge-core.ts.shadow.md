# packages\adapter-dotnet\src\utils\netcoredbg-bridge-core.ts
@source-hash: f40a72a5e9af0a73
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:26Z

## Purpose
Provides the testable core logic for a TCP-to-stdio bridge that proxies DAP (Debug Adapter Protocol) traffic between a TCP client and a `netcoredbg` child process. Extracted from `netcoredbg-bridge.ts` to enable unit testing with mock spawn and mock sockets.

## Key Exports

### `BridgeOptions` interface (L10–15)
Configuration for `createBridge`. Both fields are optional and intended for testing/injection:
- `spawnFn`: Replaces `child_process.spawn` (mock-injectable)
- `stderr`: Replaces `process.stderr` for netcoredbg stderr output

### `BridgeHandle` interface (L17–22)
Return type of `createBridge`:
- `server`: The `net.Server` listening for TCP connections
- `cleanup()`: Tears down everything — kills the child process, destroys the client socket, closes the server

### `createBridge(netcoredbgPath, port, options?)` (L32–128)
Main factory function. Steps:
1. **Listens** on `127.0.0.1:port` (L115)
2. **On first TCP connection** (L43–113): spawns `netcoredbg --interpreter=vscode` in stdio mode (L52–55)
3. **Bidirectional forwarding**:
   - TCP socket `data` → netcoredbg `stdin` (L58–62), guarded by `stdin.writable`
   - netcoredbg `stdout` → TCP socket (L65–69), guarded by `!socket.destroyed`
4. **stderr passthrough**: netcoredbg stderr written to `stderrStream` verbatim (L77–79); explicitly NOT forwarded as DAP (comment at L71–76 explains standalone NPX bundle constraint and upstream line-buffering by `GenericAdapterManager`)
5. **Single-client enforcement**: second connection is immediately destroyed (L45–48)
6. **Lifecycle events**:
   - netcoredbg `exit` → graceful `socket.end()` + `server.close()` (L82–87)
   - netcoredbg `error` → logs to stderr, destroys socket, closes server (L89–95)
   - socket `close` → ends stdin, kills netcoredbg, closes server (L98–104)
   - socket `error` → same as socket `close` (L106–112)
   - server `error` → logs to stderrStream (L117–119)
7. **Returns** `{ server, cleanup }` (L127)

## Architecture Notes
- **Dependency injection** pattern: `spawnFn` and `stderr` overrides allow full unit testing without real processes or network
- **Single-client design** mirrors `netcoredbg --server` behavior (comment L44)
- **Standalone constraint**: deliberately avoids importing `@debugmcp/shared` so this file can be bundled as a dependency-free `.js` in the NPX bundle (L72–76)
- `netcoredbg` and `client` are captured in closure (L40–41), not struct fields
- `stdout!` and `stderr!` non-null assertions at L65, L77 are intentional; safe because `stdio: ['pipe','pipe','pipe']` guarantees these streams exist

## Dependencies
- `net` (Node.js stdlib): TCP server and sockets
- `child_process` (Node.js stdlib): `spawn`, `ChildProcess`, `SpawnOptions`