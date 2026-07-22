# packages\adapter-java\java\JdiDapServer.java
@source-hash: 5db809bf607a8a25
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:08Z

## JdiDapServer — Minimal DAP Server over JDI

Single-file, zero-dependency Java Debug Adapter Protocol (DAP) server that bridges a DAP client (e.g., VS Code) to a target JVM via the Java Debug Interface (JDI). Listens on a TCP port, speaks Content-Length-framed JSON DAP messages, and drives JDI to control the target JVM.

---

### Architecture Overview

- **Entry point**: `main()` (L74) parses `--port`, `--debug`, `--owner-pid`, `--session-tag` CLI args, registers a SIGTERM shutdown hook that calls `cleanup()`, then calls `run(port)`.
- **Transport**: Single-client TCP server on loopback (L118). Reads DAP messages with `readDapMessage()` (L148) using Content-Length framing. Sends with `sendDapMessage()` (L193), synchronized on `clientOut`.
- **Message dispatch**: `handleMessage()` (L210) routes DAP `request` commands via a `switch` to handlers.
- **JDI event loop**: `startEventLoop()` (L1250) runs a daemon thread consuming `EventQueue`. Handles: `BreakpointEvent`, `StepEvent`, `ClassPrepareEvent`, `VMStartEvent`, `ThreadStartEvent`, `ThreadDeathEvent`, `VMDeathEvent`, `VMDisconnectEvent`, `ExceptionEvent`.
- **Expression evaluator**: Inner static class `ExprEvaluator` (L1698–2629) — recursive-descent parser/evaluator for Java-like expressions in a suspended thread context, using JDI `invokeMethod`.
- **JSON**: Inner static class `JsonParser` (L2632–2760) — minimal recursive-descent JSON parser; `writeJson()` (L1624) handles serialization.

---

### Key State

| Field | Type | Role |
|---|---|---|
| `vm` (L30) | `VirtualMachine` | Active JDI VM connection (volatile) |
| `launchedProcess` (L31) | `Process` | Non-null only in launch mode |
| `nextVarRef` / `varRefMap` (L36–37) | `AtomicInteger` / `ConcurrentHashMap` | Variable references for expandable objects |
| `scopeRefMap` (L39) | `ConcurrentHashMap<Integer, long[]>` | Maps scope var-ref → `[threadId, frameIndex]` |
| `threadFrameCache` (L41) | `ConcurrentHashMap<Long, List<StackFrame>>` | Cached stack frames per thread; cleared on resume/step |
| `frameIdMap` (L45) | `ConcurrentHashMap<Integer, long[]>` | Frame ID → `[threadId, frameIndex]` lookup table |
| `deferredBreakpoints` (L52) | `ConcurrentHashMap<String, Map<String, Object>>` | Breakpoints deferred until class load; keyed by `sourcePath` |
| `sourcePathMap` (L54) | `ConcurrentHashMap<String, String>` | `className → sourcePath` for source resolution |
| `launchSuspended` (L59) | `volatile boolean` | True after launch until `configurationDone` |
| `lastStopAllThreads` (L61) | `volatile boolean` | Tracks suspension scope for next `continue` |
| `ownerPid` / `sessionTag` (L71–72) | `static long/String` | Stamped as `-D` props on spawned JVM for orphan detection |

---

### DAP Command Handlers

| Command | Handler | Lines |
|---|---|---|
| `initialize` | `handleInitialize` | L254 — advertises capabilities |
| `attach` | `handleAttach` | L272 — SocketAttach connector, optional `stopOnEntry` suspend |
| `launch` | `handleLaunch` | L300 — spawns JVM with JDWP agent, retries attach up to 10s |
| `setBreakpoints` | `handleSetBreakpoints` | L516 — clears old BPs by `jdi-bp-source` tag, sets or defers |
| `configurationDone` | `handleConfigurationDone` | L703 — resumes or fires `entry` stopped event |
| `threads` | `handleThreads` | L733 |
| `stackTrace` | `handleStackTrace` | L750 — populates `threadFrameCache` |
| `scopes` | `handleScopes` | L799 — allocates scope var-ref in `scopeRefMap` |
| `variables` | `handleVariables` | L828 — resolves scope or object/array ref |
| `continue` | `handleContinue` | L975 — single-thread or all-thread resume based on `lastStopAllThreads` |
| `pause` | `handlePause` | L1005 |
| `next`/`stepIn`/`stepOut` | `handleStep` | L1037 — one-shot `StepRequest` |
| `disconnect` | `handleDisconnect` | L1066 |
| `terminate` | `handleTerminate` | L1072 |
| `evaluate` | `handleEvaluate` | L1077 — delegates to `ExprEvaluator` |
| `setExceptionBreakpoints` | `handleSetExceptionBreakpoints` | L1126 — supports `caught`/`uncaught` filters |
| `redefineClasses` | `handleRedefineClasses` | L1154 — scans `.class` files by mtime, calls `vm.redefineClasses()` |
| `source` | inline | L239 — returns empty content |

---

### Breakpoint System

- **Immediate**: `setBreakpointOnClass()` (L657) uses `locationsOfLine()` and tags each `BreakpointRequest` with `jdi-bp-source` property for scoped cleanup.
- **Deferred**: Stores in `deferredBreakpoints` + registers `ClassPrepareRequest` with wildcard filter `"*className"` and inner class filter `"className$*"`.
- **Class load**: `handleClassPrepared()` (L1364) matches loaded class against deferred entries (simple name, FQCN, inner-class outer stripping), then calls `setBreakpointOnClass()` and sends `breakpoint` changed event.
- **Conditional**: Condition string stored as property on `BreakpointRequest`; evaluated via `ExprEvaluator` in `evaluateCondition()` (L1421) on each hit.
- **Suspend policy**: `"thread"` → `SUSPEND_EVENT_THREAD`; default → `SUSPEND_ALL`.

---

### ExprEvaluator (L1698–2629)

Tokenizer (`tokenize()` L1748) produces `Token` list; parser hierarchy: `parseExpression` → `parseOr` → `parseAnd` → `parseEquality` → `parseComparison` → `parseAddition` → `parseMultiplication` → `parseUnary` → `parsePostfix` → `parsePrimary`.

Supports: literals (int/long/float/double/string/char/boolean/null), `this`, local variables, field access, method invocation (instance + static), array indexing, `instanceof`, arithmetic, string concatenation, comparisons, `&&`/`||`/`!`.

JDI invocations use `ObjectReference.INVOKE_SINGLE_THREADED`.

Unboxing (`unbox()` L2490) invokes boxed-type accessor methods via JDI to get primitive `Value`.

---

### Launch Mode Orphan Tagging (L342–353)

Spawned JVM receives `-Dmcp.debugger.jvm=true`, `-Dmcp.debugger.owner_pid=<ownerPid>`, `-Dmcp.debugger.session_tag=<sessionTag>` as system properties. These are visible in process cmdline scans so a future mcp-debugger startup can detect and reap orphaned JVMs.

---

### Source Path Resolution (L1475)

`resolveSourcePath()` checks `sourcePathMap` by class base name first, then falls back to reconstructing `packagePath/SourceFile.java`.

---

### Frame ID Encoding (L1465–1473)

Uses a lookup table (`frameIdMap`) rather than arithmetic encoding: `encodeFrameId()` allocates a sequential ID and stores `[threadId, frameIndex]`. Reset by `clearFrameCache()` (L1497) on every resume/step.

---

### Cleanup (L1510)

`cleanup()` is synchronized; disposes `vm` and forcibly destroys `launchedProcess`. Called from shutdown hook, `handleDisconnect`, and `handleTerminate`.

---

### JSON Utilities (L2764–2838)

Static helpers: `str`, `strOr`, `intVal`, `longVal`, `intValOrNull`, `boolVal`, `map`, `list`, `asMap`, `mapOf`, `log`, `logVerbose`.
