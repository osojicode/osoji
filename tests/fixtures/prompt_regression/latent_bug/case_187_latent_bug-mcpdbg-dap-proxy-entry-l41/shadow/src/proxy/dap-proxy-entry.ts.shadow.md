# src\proxy\dap-proxy-entry.ts
@source-hash: 495a09fb648e87fd
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:21Z

## DAP Proxy Entry Point (`src/proxy/dap-proxy-entry.ts`)

Production entry point for the DAP (Debug Adapter Protocol) proxy worker process. Performs execution mode detection at module load time and conditionally auto-starts the proxy runner.

### Purpose
This file is the **production auto-execution entry** for the DAP proxy worker. It is intentionally designed to auto-execute with **no test environment checks** (L27 comment), relying solely on `shouldAutoExecute` to guard startup.

### Execution Flow (Module-Level, L20–52)
1. **Detection (L20):** Calls `detectExecutionMode()` — returns an object with `{ isDirectRun, hasIPC, isWorkerEnv }`.
2. **Diagnostic logging (L22–25):** Emits startup diagnostics to `stderr` including Node.js version and CWD.
3. **Conditional auto-start (L28–52):** If `shouldAutoExecute(executionMode)` is truthy:
   - Creates production dependencies via `createProductionDependencies()` (L32)
   - Creates a console logger via `createConsoleLogger()` (L33)
   - Instantiates `ProxyRunner(dependencies, consoleLogger)` (L36)
   - Calls `runner.setupGlobalErrorHandlers(...)` (L39–42):
     - Stop callback: `() => runner.stop()`
     - Session ID accessor: `() => runner.getWorker()?.currentSessionId ?? 'unknown'` — accesses via `unknown as Record<string,string>` cast to reach a private field (L41)
   - Calls `runner.start()` (L45), with `.catch()` that logs error and calls `process.exit(1)` (L47)
4. **Else branch (L52):** Logs non-execution reason to `stderr`.

### Three Detection Methods (documented at L7–11)
| Method | Field | Description |
|---|---|---|
| Direct execution | `isDirectRun` | Script run directly via `node` |
| IPC presence | `hasIPC` | Spawned as child process with IPC channel |
| Environment flag | `isWorkerEnv` | `DAP_PROXY_WORKER=true` env var set by bootstrap |

### Key Design Decisions
- **No test environment guards:** Comment at L27 explicitly notes this is intentional — detection is handled entirely by `shouldAutoExecute`.
- **Private field access via cast (L41):** `runner.getWorker()` result is cast through `unknown as Record<string, string>` to access `currentSessionId`, which is a private field. This is a workaround for TypeScript visibility constraints.
- **All logic is module-level:** No exported symbols; this file is purely a side-effectful entry point.
