# examples\javascript\test_javascript_debug.js
@source-hash: cc36b9c79f9ab95c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:54Z

## Overview
A self-contained Node.js script demonstrating basic JavaScript constructs (recursion, iteration, array processing) intended as a debugging/testing example. Executes immediately upon invocation with no external dependencies.

## Key Symbols

### `factorial(n)` (L6–12)
Recursive factorial implementation. Base case: `n <= 1` returns `1`. Called with `5` in `main()`, producing `120`.

### `sumList(numbers)` (L14–21)
Iterates over a numeric array using `for...of`, accumulating a total. Returns the sum.

### `processData(data)` (L23–31)
Maps each element of a numeric array by multiplying by `2` using a `for...of` loop and `Array.push`. Returns the new array.

### `main()` (L33–58)
Orchestrates all utility functions:
- Declares `x=10`, `y=20`, `z=30` (L35–37)
- Calls `factorial(5)` → `120` (L40)
- Calls `sumList([1,2,3,4,5])` → `15` (L45)
- Calls `processData([10,20,30])` → `[20,40,60]` (L50)
- Computes `final = z * factResult` → `30 * 120 = 3600` (L54)
- Returns `final` (L57)

## Module-Level Execution (L61–62)
Script runs `main()` immediately and logs the final result. Acts as its own entry point (shebang `#!/usr/bin/env node` at L1).

## Architectural Notes
- No imports or external dependencies — fully self-contained.
- No exports; not designed for `require`/`import` by other modules.
- All output via `console.log` with template literals.
- `z` (L37) is computed but only used in the `final` computation (L54); `sumResult` (L45) is logged but not used in further computation.
