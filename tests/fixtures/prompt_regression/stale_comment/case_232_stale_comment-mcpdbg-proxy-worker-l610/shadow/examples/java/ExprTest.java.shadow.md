# examples\java\ExprTest.java
@source-hash: ceaa7f210690dea3
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:46Z

## Purpose
JDI bridge test fixture for expression evaluation. Designed to be compiled with debug symbols (`javac -g`) and run under a Java debugger. A breakpoint at L37 exercises all expression types the JDI bridge needs to evaluate, and the interface hierarchy tests the `instanceof` fix from Issue 14.

## Key Elements

### Interfaces (L11–12)
- **`Greeter`** (L11): Single-method interface with `greet(String who): String`
- **`FormalGreeter`** (L12): Extends `Greeter` with no additional methods — forms a two-level interface hierarchy used to test `instanceof` resolution (Issue 14)

### Class `ExprTest` (L14–43)
Implements `FormalGreeter` (and transitively `Greeter`). Contains a representative set of field and variable types to exercise debugger expression evaluation:

**Instance Fields (L16–21):**
| Field | Type | Value | Purpose |
|---|---|---|---|
| `instanceField` | `int` | `42` | Primitive int field access |
| `name` | `String` | `"test"` | String field access |
| `numbers` | `int[]` | `{10, 20, 30}` | 1D array indexing |
| `matrix` | `int[][]` | `{{1,2},{3,4}}` | 2D array indexing |
| `flag` | `boolean` | `true` | Boolean field access |
| `greeterRef` | `Greeter` | `this` | Interface-typed reference (for `instanceof` tests) |

**Methods:**
- `add(int a, int b): int` (L23–25) — simple arithmetic, tests method invocation with primitive args
- `greet(String who): String` (L27–29) — interface implementation, returns `"Hello, " + who`
- `run(): void` (L31–38) — sets up local variables of varied types (`int`, `double`, `String`, `Integer`/boxed) for debugger inspection at the breakpoint on L37
- `main(String[] args): void` (L40–42) — entry point; instantiates `ExprTest` and calls `run()`

### Breakpoint Target (L37)
The `println` on L37 is the intended breakpoint line. At this point the debugger frame will have in scope:
- `x` (`int` = 10)
- `pi` (`double` = 3.14)
- `msg` (`String` = `"hello"`)
- `boxed` (`Integer` = 42)
- `this` (with all instance fields above)

## Architectural Notes
- **Compile flag `-g`** is required to retain local variable debug info; without it, `x`, `pi`, `msg`, and `boxed` won't be visible to JDI.
- The `greeterRef = this` assignment (L21) combined with the `FormalGreeter → Greeter` hierarchy allows tests of `instanceof` across interface levels without creating separate concrete classes.
- No external dependencies; self-contained single-file compilation (note: `Greeter` and `FormalGreeter` are package-private top-level interfaces in the same file, valid in Java).
- This file is a **test fixture/data file**, not a unit test — it is exercised externally by a JDI-based debugger/bridge test harness.