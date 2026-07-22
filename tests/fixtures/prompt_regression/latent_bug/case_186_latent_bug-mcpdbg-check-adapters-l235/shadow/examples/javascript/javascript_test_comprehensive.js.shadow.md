# examples\javascript\javascript_test_comprehensive.js
@source-hash: 3097d163e8b22c79
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:59Z

## Overview
A self-contained JavaScript script designed for MCP debugger testing. It exercises common debugging scenarios: variable inspection, array operations, recursion, iteration, object literals, conditional branches, and arrow functions. Entry point is `main()` called at module level (L81).

## Key Symbols

### `fibonacci(n)` (L6–12)
Recursive Fibonacci calculation. Base case: `n <= 1` returns `n`. Used in `main()` at L50 with `n=5` (expected result: 5).

### `calculateSum(numbers)` (L14–21)
Iterates over a numeric array with `for...of`, accumulates into `total`. Returns the sum. Called at L46 with `[1,2,3,4,5]` (expected: 15).

### `factorial(n)` (L23–33)
Iterative factorial using a `for` loop from `i=2` to `n`. Base case: `n <= 1` returns `1`. Called at L54 with `n=5` (expected: 120).

### `main()` (L35–78)
Orchestrates seven test scenarios logged to stdout:
- **Test 1** (L39–42): Simple arithmetic (`x=10, y=20, z=30`)
- **Test 2** (L45–47): Array sum via `calculateSum`
- **Test 3** (L50–51): Recursive Fibonacci
- **Test 4** (L54–55): Iterative factorial
- **Test 5** (L58–63): Object literal with `name`, `age`, `city` fields
- **Test 6** (L66–70): Conditional branch on `z > 25` (always true since z=30)
- **Test 7** (L73–75): Inline arrow function `square = (n) => n * n`

### `square` (L73)
Arrow function defined locally in `main()`. Not exported; used only for Test 7.

## Execution
Script is directly executable (`#!/usr/bin/env node`, L1). `main()` is invoked unconditionally at L81. No imports or external dependencies.

## Architectural Notes
- Pure computation — no I/O beyond `console.log`, no async, no modules.
- Intended as a debugger breakpoint/step-through target; all functions are named and straightforward.
- The conditional at L66 (`z > 25`) is always true (`z = 30`), making the `else` branch (L69) dead code in practice — though this may be intentional for debugger scenario coverage.