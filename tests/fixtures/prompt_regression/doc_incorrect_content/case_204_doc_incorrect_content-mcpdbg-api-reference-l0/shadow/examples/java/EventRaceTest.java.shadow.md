# examples\java\EventRaceTest.java
@source-hash: 72aaff2e463ebd7a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:02Z

## EventRaceTest (L13–39)

A JVM debugger test fixture designed to reproduce a specific race condition in JDWP event handling: a `ClassPrepareEvent` incorrectly resuming a thread that is suspended at a breakpoint when both events arrive in the same `EventSet`.

### Purpose
This class acts as the **debuggee** (target JVM process) for a debugger integration test. It is not a JUnit/TestNG test itself — it is launched by an external debugger client that attaches via JDI/JDWP and sets breakpoints. The test validates that a `ClassPrepareEvent` for `LateLoadedHelper` does not prematurely resume the thread suspended at a breakpoint.

### Key Elements

- **`compute(int a, int b)` (L19–22):** Intentional breakpoint target. Sets a breakpoint at L21 (`int result = a + b`) with `suspendPolicy="thread"`. The comment on L20 states "line 21" but the actual assignment is on L20 — **off-by-one in the comment**. Called from `main()` at L29.

- **`main(String[] args)` (L24–38):**
  1. Prints startup message and sleeps 2 seconds (L25–26) to give the external debugger time to attach and set breakpoints before execution proceeds.
  2. Calls `compute(10, 20)` at L29 — this should trigger the breakpoint.
  3. References `LateLoadedHelper.greet("World")` at L34 — triggers lazy class loading of `LateLoadedHelper`, which fires a `ClassPrepareEvent` if the debugger has a `ClassPrepareRequest` for that class.
  4. The race condition window: if the breakpoint at L29 and the `ClassPrepareEvent` for `LateLoadedHelper` land in the same `EventSet`, a buggy debugger may resume the breakpointed thread when processing the `ClassPrepareEvent`.

### Race Condition Mechanics
- `Thread.sleep(2000)` (L26): Allows an attaching debugger to set up both a `BreakpointRequest` (in `compute`) and a `ClassPrepareRequest` (for `LateLoadedHelper`) before `main()` proceeds.
- `LateLoadedHelper` is intentionally **not referenced** until after the breakpoint fires (L34), ensuring it is truly "late loaded."
- The `suspendPolicy="thread"` (mentioned in class-level Javadoc, L11) is critical — it is what allows the race: a `ClassPrepareEvent` with its own suspend policy may conflict with the breakpoint's thread-level suspension.

### Dependencies
- **`LateLoadedHelper`** (external class, not defined here): Must have a static method `greet(String)` returning a `String`. Its class file must **not** be loaded before L34 is reached. Must be a separate class to trigger `ClassPrepareEvent`.
- **JDI/JDWP debugger** (external): Sets breakpoints and `ClassPrepareRequest`; validates thread suspension state after each event.

### Comment Accuracy Note
- L20 comment says "line 21 — breakpoint target" but the statement `int result = a + b` compiles to bytecode on L20. This off-by-one may cause a debugger test to set the breakpoint at the wrong line number.
- L34 comment says "line 33" but the `LateLoadedHelper.greet(...)` call is on L34 — another off-by-one that could mislead a debugger test setting a breakpoint there.