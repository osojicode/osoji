# examples\java\InnerClassTest.java
@source-hash: d16fc75cfd8b9ce1
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:35Z

## Purpose
A minimal Java test fixture designed to validate JDI (Java Debug Interface) bridge behavior for inner class breakpoints. Specifically tests `ClassPrepareRequest` with `"$*"` suffix pattern and `"$"`-stripping logic in `handleClassPrepared` for resolving breakpoints inside non-static inner classes.

## Structure

### `InnerClassTest` (L11–26) — Outer class
Top-level public class. Entry point via `main`. Serves as the enclosing instance for `Inner`.

### `InnerClassTest.Inner` (L13–18) — Non-static inner class
- `compute(int a, int b)` (L14–17): Adds `a + b`, stores result in local variable `result` (L15), returns it. **Line 15 is the designated breakpoint target** (`// BREAKPOINT HERE`). Compiled as `InnerClassTest$Inner.class`.

### `main(String[] args)` (L20–25)
1. Instantiates outer class (L21).
2. Instantiates `Inner` via outer instance (`outer.new Inner()`) (L22) — requires an enclosing instance, which is the key JDI class-prepare trigger.
3. Calls `inner.compute(7, 8)` (L23).
4. Prints result to stdout: `"Sum: 15"` (L24).

## Key Testing Concerns
- **Inner class naming**: JVM compiles `Inner` as `InnerClassTest$Inner`. A JDI `ClassPrepareRequest` filtered on `"InnerClassTest$*"` must match this class.
- **`$`-stripping**: The JDI bridge's `handleClassPrepared` handler must strip the `$`-prefixed suffix when mapping the prepared class back to the source-level breakpoint request.
- **Non-static inner class**: Requires an enclosing instance; the instantiation pattern (`outer.new Inner()`) is intentional and representative of real-world usage.

## Usage
```
javac -g InnerClassTest.java   # -g preserves line number tables needed for breakpoints
java InnerClassTest
```
Expected output: `Sum: 15`