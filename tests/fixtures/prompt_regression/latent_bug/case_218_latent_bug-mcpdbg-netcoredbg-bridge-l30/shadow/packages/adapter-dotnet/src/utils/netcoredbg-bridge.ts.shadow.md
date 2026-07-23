# packages\adapter-dotnet\src\utils\netcoredbg-bridge.ts
@source-hash: 8f0027e0e50cd9a8
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:51Z

## `packages/adapter-dotnet/src/utils/netcoredbg-bridge.ts`

### Purpose
Thin CLI entry point that parses arguments and delegates to `createBridge` from `netcoredbg-bridge-core`. Exists to work around a netcoredbg `--server=PORT` TCP drop bug by bridging a TCP listener to netcoredbg's stdio DAP interface.

### Architecture
- **Entry point only** — all logic lives in `netcoredbg-bridge-core.js`. This file parses `process.argv`, validates inputs, calls `createBridge`, and registers a `SIGTERM` handler.
- **No DAP parsing** — operates as a pure byte-level forwarder (documented in file header, L12).

### Key Execution Flow
1. **Argument parsing (L19–20):** Slices `process.argv` to extract `<netcoredbg-path>` and `<port>` as positional args.
2. **Validation (L22–25):** If either arg is missing/falsy (including `port === 0` or `NaN`), writes usage to stderr and exits with code 1.
3. **Bridge creation (L27):** Calls `createBridge(netcoredbgPath, port)`, destructures `{ cleanup }` from the result.
4. **Signal handling (L30–32):** Registers `SIGTERM` listener to invoke `cleanup()` for graceful shutdown.

### Invocation
Spawned as a child process by the adapter or proxy:
```
node netcoredbg-bridge.js <netcoredbg-path> <port>
```

### Dependencies
- `./netcoredbg-bridge-core.js` — provides `createBridge(path, port): { cleanup }` (L17)

### Critical Constraints
- `port` parsed via `parseInt(portStr, 10)` (L20). A value of `0` is treated as falsy by the `!port` guard (L22), so port 0 is effectively rejected.
- No `SIGINT` handler registered — only `SIGTERM` triggers cleanup. Ctrl-C will not call `cleanup()`.
- `NaN` from a non-numeric port string also passes the `!port` guard correctly (NaN is falsy).