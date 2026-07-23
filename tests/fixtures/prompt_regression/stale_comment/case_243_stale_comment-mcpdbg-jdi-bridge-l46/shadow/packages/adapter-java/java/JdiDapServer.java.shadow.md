# packages\adapter-java\java\JdiDapServer.java
@source-hash: c6711e45460b7f61
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:36:18Z

## JdiDapServer

Single-file, zero-dependency DAP (Debug Adapter Protocol) server that bridges a TCP DAP client to a target JVM via JDI (Java Debug Interface). Accepts one TCP client per run, speaks Content-Length-framed JSON DAP over that socket, and manages the JVM lifecycle (launch or attach).

### Entry Point
- `main` (L74-115): Parses `--port`, `--debug`, `--owner-pid`, `--session-tag` CLI args; registers a SIGTERM shutdown hook that calls `cleanup()`; calls `run(port)`.
- `run` (L117-144): Binds a loopback `ServerSocket`, accepts exactly one client, then drives the DAP read loop until EOF or `running=false`.

### Top-Level State
| Field | Type | Purpose |
|---|---|---|
| `seq` | `AtomicInteger` | DAP sequence number counter (L27) |
| `vm` | `volatile VirtualMachine` | JDI VM handle; null when disconnected (L30) |
| `launchedProcess` | `volatile Process` | Non-null only in launch mode (L31) |
| `nextVarRef` / `varRefMap` | AtomicInt + ConcurrentHashMap | Variable reference IDs → `ObjectReference` (L36-37) |
| `scopeRefMap` | ConcurrentHashMap | Scope ref IDs → `[threadId, frameIndex]` (L39) |
| `threadFrameCache` | ConcurrentHashMap | Per-thread cached `StackFrame` list (L41) |
| `nextFrameId` / `frameIdMap` | AtomicInt + ConcurrentHashMap | Frame ID lookup table (L44-45) |
| `nextBreakpointId` | `AtomicInteger` | Monotonic breakpoint ID (L48) |
| `deferredBreakpoints` | ConcurrentHashMap | sourcePath → bpInfo; holds breakpoints pending class load (L52) |
| `sourcePathMap` | ConcurrentHashMap | className → DAP sourcePath for source resolution (L54) |
| `lastStopAllThreads` | `volatile boolean` | Tracks whether the last stop suspended all threads; drives `continue` behavior (L61) |
| `ownerPid` / `sessionTag` | static long / String | Orphan-reap markers stamped as `-D` JVM properties on launched processes (L71-72) |

### DAP Transport (L146-206)
- `readDapMessage` (L148): Reads `Content-Length:` header, then body bytes; delegates to `parseJson`.
- `readLine` (L174): Handles `\r\n` and bare `\n` line endings.
- `sendDapMessage` (L193): Synchronized; writes `Content-Length: N\r\n\r\n` + JSON body.

### Message Dispatch (L210-250)
`handleMessage` dispatches on `command` string to individual handlers. Unrecognized commands return an error response. All handler exceptions are caught and returned as error responses.

### DAP Handlers
| Handler | Lines | Notes |
|---|---|---|
| `handleInitialize` | L254-270 | Returns capability map; sends `initialized` event |
| `handleAttach` | L272-298 | Attaches via `com.sun.jdi.SocketAttach`; optional `stopOnEntry` suspends VM |
| `handleLaunch` | L300-416 | Finds free port for JDWP; spawns JVM with orphan-reap `-D` markers; forwards stdout/stderr as DAP output events; retries JDI attach for 10s; sets `launchSuspended=true` |
| `handleSetBreakpoints` | L516-655 | Clears then re-sets breakpoints tagged with `jdi-bp-source` property; defers via `ClassPrepareRequest` if class not loaded; handles inner classes with `ClassName$*` filter |
| `setBreakpointOnClass` | L657-701 | Sets a `BreakpointRequest` on a specific `ReferenceType`; stores condition in request property; supports `thread` suspend policy |
| `handleConfigurationDone` | L703-731 | Sends stopped("entry") or resumes VM based on `stopOnEntry` flag |
| `handleThreads` | L733-748 | Lists all JDI threads |
| `handleStackTrace` | L750-797 | Fetches and caches thread frames; resolves source paths |
| `handleScopes` | L799-826 | Allocates a scope ref mapping to `[threadId, frameIndex]`; returns single "Locals" scope |
| `handleVariables` | L828-865 | Looks up scope ref → frame locals or varRef → object/array fields |
| `handleContinue` | L975-1003 | Resumes single thread or all threads depending on `lastStopAllThreads` |
| `handlePause` | L1005-1035 | Suspends specific thread or entire VM |
| `handleStep` | L1037-1064 | Creates one-shot `StepRequest` (STEP_LINE) with depth OVER/INTO/OUT |
| `handleDisconnect` | L1066-1070 | Sends response then `cleanup()`, sets `running=false` |
| `handleTerminate` | L1072-1075 | `cleanup()` then response |
| `handleEvaluate` | L1077-1124 | Resolves frame from cache; delegates to `ExprEvaluator` |
| `handleSetExceptionBreakpoints` | L1126-1150 | Replaces all `ExceptionRequest`s based on `caught`/`uncaught` filter strings |
| `handleRedefineClasses` | L1154-1246 | Walks `classesDir` recursively; filters by `sinceTimestamp` mtime; calls `vm.redefineClasses()` per matching class |

### JDI Event Loop (L1250-1362)
`startEventLoop` (L1250): Daemon thread consuming `EventQueue`. Key behaviors:
- `BreakpointEvent`: evaluates conditional expression via `ExprEvaluator`; sends `stopped("breakpoint")`
- `StepEvent`: deletes one-shot request; sends `stopped("step")`
- `ClassPrepareEvent`: calls `handleClassPrepared` to install deferred breakpoints; only resumes if no stop event in same `EventSet`
- `VMStartEvent`: does NOT resume (configurationDone is responsible — L1302-1305)
- `ThreadStartEvent` / `ThreadDeathEvent`: sends `thread` events
- `VMDeathEvent` / `VMDisconnectEvent`: sends `terminated` event, sets `running=false`
- `ExceptionEvent`: sends `stopped("exception")`

`handleClassPrepared` (L1364-1419): Matches prepared `ReferenceType` against `deferredBreakpoints` by FQN, simple name, or outer-class prefix for inner classes. Installs breakpoints and sends `breakpoint("changed")` verified events.

### Expression Evaluator — `ExprEvaluator` (L1698-2641)
Inner static class. Recursive-descent parser+evaluator for Java-like expressions using JDI. Tokenizer (L1748-1918) handles integer/long/float/double/hex/binary literals, strings, chars, keywords (`true`, `false`, `null`, `this`, `instanceof`), all standard operators.

**Parser precedence levels** (low to high):
1. `parseOr` / `parseAnd` — logical operators (L1957, L1973); **known limitation**: RHS always evaluated even when short-circuited (documented at L1952-1955, L1971-1972)
2. `parseEquality` (L1987), `parseComparison` (L1997) — includes `instanceof`
3. `parseAddition` / `parseMultiplication` (L2019, L2029)
4. `parseUnary` (L2039), `parsePostfix` (L2056)
5. `parsePrimary` (L2081) — literals, variables, `this`, grouped expressions, bare method calls

**JDI helpers:**
- `resolveVariable` (L2173): locals → `this` fields → static fields
- `accessField` (L2195): handles `array.length` specially; throws for primitives/null
- `invokeMethod` (L2217): filters by arg count; best-effort overload resolution via `bestMatch`
- `invokeStaticMethod` (L2259): requires `ClassType` cast to call static methods
- `unbox` (L2502): invokes `intValue()` etc. via JDI on wrapper types
- `isSubtypeOf` (L2344): recursive JDI type hierarchy walk

### JSON Infrastructure (L1610-2851)
- `JsonParser` (L2644-2772): Minimal recursive-descent parser; numbers parsed as `int` when in int range, else `long`, else `Double` for floats.
- `writeJson` (L1624): Handles `null`, `Boolean`, `Number` (avoids scientific notation for whole doubles), `String` (full escape), `Map`, `List`; falls back to `toString()` for other types.
- Map helpers (`str`, `strOr`, `intVal`, `longVal`, `intValOrNull`, `boolVal`, `map`, `list`, `asMap`, `mapOf`) at L2776-2842.

### Breakpoint Architecture
1. `setBreakpoints` DAP request: tags each `BreakpointRequest` with `jdi-bp-source = sourcePath` property for precise cleanup (prevents cross-package name collisions, e.g. `com.a.Foo` vs `com.b.Foo`).
2. Deferred via `ClassPrepareRequest` with filter `"*ClassName"` and `"ClassName$*"` for inner classes.
3. `registerPendingBreakpoints` (L422-482): called after VM connect for pre-connect `setBreakpoints` calls.
4. `handleClassPrepared` (L1364): installs deferred breakpoints when class loads, sends verified event.

### Source Path Resolution (L1475-1495)
`resolveSourcePath`: checks `sourcePathMap` (populated by `handleSetBreakpoints`) by base class name, then falls back to `packagePath/sourceName` construction.

### Cleanup (L1510-1523)
`cleanup` is `synchronized` to prevent race between shutdown hook and `disconnect`/`terminate` handlers. Disposes JDI VM and force-kills `launchedProcess`.

### Orphan Reap Markers (L66-72, L346-353)
Launched JVMs are stamped with `-Dmcp.debugger.jvm=true`, `-Dmcp.debugger.owner_pid=<pid>`, `-Dmcp.debugger.session_tag=<uuid>` so that a future mcp-debugger startup can detect and kill orphaned JVMs whose owner process has died.
