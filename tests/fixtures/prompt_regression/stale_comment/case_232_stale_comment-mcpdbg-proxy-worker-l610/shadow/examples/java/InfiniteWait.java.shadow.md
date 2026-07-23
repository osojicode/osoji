# examples\java\InfiniteWait.java
@source-hash: 82a4fe5fee47467e
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:43Z

## Purpose
A minimal Java test fixture for attach-mode JDWP debugging. Provides well-known local variables and line-numbered breakpoint targets so an external debugger (or JDI bridge) can attach, set breakpoints, and inspect state.

## Class: `InfiniteWait` (L11–35)
Single public class with no instance state. All methods are `static`. Despite the class name, the program does **not** loop or wait indefinitely — it sleeps 2 seconds then exits. The name reflects an earlier design intent (suspend-mode JDWP pauses the JVM at startup, so the program itself doesn't need to spin).

## Methods

### `compute(int a, int b)` (L13–16)
- Adds two integers; stores result in local `result` (L14).
- **Breakpoint target: L14** — local variable `result` is inspectable here.
- Returns `result` (L15).

### `format(String label, int value)` (L18–21)
- Concatenates `label + ": " + value` into local `String text` (L19).
- **Breakpoint target: L19** — local variable `text` is inspectable here.
- Returns `text` (L20).

### `main(String[] args)` (L23–34)
Execution flow:
1. Prints `"Waiting for debugger..."` (L24).
2. `Thread.sleep(2000)` (L28) — 2-second pause annotated as time for debugger attach and breakpoint setup via `ClassPrepareRequest`.
3. Declares `int x = 42` (L29) and `int y = 58` (L30) — inspectable locals.
4. Calls `compute(x, y)` → `sum` (L31).
5. Calls `format("Sum", sum)` → `msg` (L32).
6. Prints `msg` (L33).

## JDWP Launch Invocation (L4–6, in javadoc)
```
java -agentlib:jdwp=transport=dt_socket,server=y,address=<port>,suspend=y -cp . InfiniteWait
```
With `suspend=y` the JVM halts before `main` runs, giving the debugger time to connect and set `ClassPrepareRequest`-based deferred breakpoints before any code executes.

## Key Architectural Notes
- **No external dependencies** — pure standard-library Java.
- Line numbers are explicitly annotated in comments (L14, L15, L19, L20, L28–32) to serve as stable breakpoint coordinates for test harnesses.
- Class name `InfiniteWait` is **misleading** relative to actual behavior (finite 2-second sleep + exit); the JDWP `suspend=y` flag is what truly pauses execution, not any program-level loop.
- Throws `Exception` from `main` to allow `Thread.sleep` without a try/catch.