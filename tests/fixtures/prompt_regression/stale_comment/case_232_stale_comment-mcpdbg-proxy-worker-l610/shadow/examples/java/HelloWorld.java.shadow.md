# examples\java\HelloWorld.java
@source-hash: 05ae337334d673a3
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:40Z

## HelloWorld (L7–29)

A minimal Java smoke-test program designed for exercising a Java debug adapter. Its primary value is as a debuggable target with well-annotated line numbers, not as application logic.

### Class: `HelloWorld` (L7–29)
Single public class containing three static methods and a deliberate 2-second startup delay to allow breakpoint setup before meaningful execution begins.

### Methods

| Method | Lines | Signature | Purpose |
|--------|-------|-----------|---------|
| `add` | L9–12 | `static int add(int a, int b)` | Adds two integers; result stored in named local `result` (L10) to provide a watchable variable at L10–11. |
| `greet` | L14–17 | `static String greet(String name)` | Concatenates a greeting string; local `greeting` (L15) is a deliberate debuggable variable. |
| `main` | L19–28 | `public static void main(String[] args) throws Exception` | Entry point; calls `Thread.sleep(2000)` (L21) explicitly to pause execution for breakpoint setup, then exercises `add` (L24) and `greet` (L25), printing results (L26–27). |

### Notable Design Decisions
- **`Thread.sleep(2000)` at L21**: Intentional 2-second pause documented inline as "pause for breakpoint setup". This is a debug-adapter testing convention, not production code.
- **Named intermediary locals** (`result` at L10, `greeting` at L15): Kept as separate variables (rather than inline returns) to give the debugger watchable/inspectable locals at specific lines.
- **Line numbers annotated inline** (L10–27): Comments like `// line 10` are present throughout `main` and helpers to make breakpoint targeting by line number unambiguous in test scenarios.
- **`throws Exception` on `main`** (L19): Broad exception declaration to allow `Thread.sleep` without a try/catch, keeping the method body flat and easy to step through.

### Compile & Run
```
javac HelloWorld.java
java HelloWorld
```
Output sequence:
1. `Starting...`
2. (2-second pause)
3. `Hello, World!`
4. `Sum: 30`