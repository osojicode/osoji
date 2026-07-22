# src\proxy\dap-proxy-core.ts
@source-hash: 1fab463c9202e0b0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:09:05Z

## DAP Proxy Core

Provides the core proxy runner (`ProxyRunner`) for the DAP (Debug Adapter Protocol) proxy process. Manages process lifecycle, communication channel setup (IPC or stdin/readline), heartbeat mechanism, initialization timeout, and graceful shutdown. Also exports execution-mode detection helpers for determining whether the proxy should auto-execute.

---

### `ProxyRunnerOptions` (L21-43) — interface
Configuration for `ProxyRunner`:
- `useIPC?: boolean` — prefer IPC channel over stdin (default: use IPC if available)
- `useStdin?: boolean` — fall back to stdin/readline if IPC unavailable
- `onMessage?: (message: string) => Promise<void>` — override message handler (testing)
- `proc?: ProcessLike` — injectable process handle (default: global `process`); used for IPC, signals, exit, stdio (issue #183)

---

### `ProxyRunner` (L49-408) — class

Central orchestrator for the proxy subprocess. Wraps `DapProxyWorker` and wires it to a communication channel.

**Key fields:**
- `worker: DapProxyWorker` (L50) — handles DAP command logic
- `logger: ILogger` (L51) — injected logger
- `rl?: readline.Interface` (L52) — stdin interface (stdin mode only)
- `messageHandler?: (message: unknown) => Promise<void>` (L53) — IPC message handler, stored for removal on stop
- `isRunning: boolean` (L54) — guard against double-start and orphan-exit loops
- `_initTimeout?: NodeJS.Timeout` (L55) — 10s timeout to kill orphaned processes that never receive `init`
- `ipcMessageCounter: number` (L56) — sequential IPC message counter for diagnostics
- `heartbeatInterval?: NodeJS.Timeout` (L57) — 5s heartbeat to parent; exits on failure
- `heartbeatTickCounter: number` (L58) — heartbeat sequence number
- `disconnectHandler`, `errorHandler` (L59-60) — stored for clean removal on stop
- `proc: ProcessLike` (L61) — injectable process reference

**Constructor (L63-71):** Resolves `proc` from options (defaults to global `process`). Instantiates `DapProxyWorker` with a wrapped exit callback.

**`start(): Promise<void>` (L76-141):**
1. Guards against double-start.
2. Selects message processor: `options.onMessage` or `createMessageProcessor()`.
3. Prefers IPC channel (`setupIPCCommunication`) if `proc.send` is a function and `useIPC !== false`; otherwise falls back to stdin (`setupStdinCommunication`) unless `useStdin === false`.
4. Starts 5s heartbeat interval sending `{type: 'ipc-heartbeat-tick', ...}` via `proc.send`; on send failure, calls `stop()` then `proc.exit(1)`.
5. Sets 10s init timeout (`_initTimeout`) — exits process if no `init` command arrives.

**`stop(): Promise<void>` (L146-191):**
1. No-op if not running.
2. Immediately sets `isRunning = false` to prevent re-entrant channel-close handling.
3. Clears init timeout and heartbeat interval.
4. Calls `worker.shutdown()`.
5. Removes IPC message/disconnect/error listeners via `proc.removeListener`.
6. Closes readline interface if present.

**`getWorkerState(): ProxyState` (L196-198):** Returns current worker state.

**`getWorker(): DapProxyWorker` (L203-205):** Returns worker instance (for testing).

**`createMessageProcessor()` (L210-247) [private]:**
Returns an async closure that:
- Parses raw string via `MessageParser.parseCommand`.
- Clears `_initTimeout` on first `init` command.
- Dispatches to `worker.handleCommand(command)`.
- On error, sends `{type: 'error', ...}` via `dependencies.messageSender.send`.
- Checks if worker state is `TERMINATED`; if so, schedules `proc.exit(0)` (with 500ms delay for dry-run init).

**`setupIPCCommunication(processMessage)` (L252-326) [private]:**
- Validates `proc.send` is a function.
- Attaches `messageHandler` to `proc.on('message')`: handles string or object messages (stringifies objects), sends per-message `{type: 'ipc-heartbeat'}` acknowledgement.
- Attaches `disconnectHandler` to `proc.on('disconnect')`: calls `stop()` then `proc.exit(0)` (parent death).
- Attaches `errorHandler` to `proc.on('error')`: logs error.

**`setupStdinCommunication(processMessage)` (L331-355) [private]:**
- Creates `readline.Interface` from `proc.stdin`/`proc.stdout`.
- Wires `line` event to `processMessage`.
- Wires `close` event to `stop()` + `proc.exit(0)` if `isRunning` (parent EOF = parent gone).

**`setupGlobalErrorHandlers(errorShutdown, getCurrentSessionId)` (L360-407):**
Registers on `proc`:
- `uncaughtException` → sends error message, calls `errorShutdown()`, exits 1.
- `unhandledRejection` → sends error message (does NOT exit — may be intentional).
- `SIGTERM` → calls `errorShutdown()`, exits 0.
- `SIGINT` → calls `errorShutdown()`, exits 0.

---

### `detectExecutionMode(proc?)` (L416-429) — function

Detects how the module is being run:
- `isDirectRun`: `require.main === module` or ESM `import.meta.url` matches `proc.argv[1]`
- `hasIPC`: `proc.send` is a function
- `isWorkerEnv`: `proc.env.DAP_PROXY_WORKER === 'true'`

Default `proc` is global `process`. Returns `{ isDirectRun, hasIPC, isWorkerEnv }`.

---

### `shouldAutoExecute(mode)` (L434-436) — function

Returns `true` if any of `isDirectRun`, `hasIPC`, or `isWorkerEnv` is truthy. Used by entry points to decide whether to auto-start the proxy.

---

### Architecture Notes
- **IPC preferred over stdin:** IPC is tried first if `proc.send` exists and `useIPC !== false`.
- **Dual heartbeat design:** Both a per-message acknowledgement (`ipc-heartbeat`) and a periodic tick (`ipc-heartbeat-tick`) are sent to parent. Only the tick failure causes shutdown.
- **isRunning guard:** Critical for preventing the readline `close` event (triggered by `stop()`) from re-entering the shutdown path.
- **`proc` injection:** All process interactions go through `this.proc`, enabling full unit test isolation without touching the real process.
- **`_initTimeout`:** Prevents orphaned proxy processes when a parent spawns a child but never sends an `init` command.