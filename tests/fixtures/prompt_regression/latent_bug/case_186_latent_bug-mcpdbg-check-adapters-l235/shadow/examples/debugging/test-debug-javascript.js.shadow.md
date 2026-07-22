# examples\debugging\test-debug-javascript.js
@source-hash: 7b3844907faa5a88
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:50Z

## Overview
A standalone Node.js script designed as a debugging target for an MCP debugger. It exercises several common code patterns — arithmetic, array iteration, recursion, and object construction — making it useful for setting breakpoints, inspecting variables, and stepping through execution.

## Key Symbols

### `calculateProduct(a, b)` (L6–11)
Multiplies two numbers, logs the operation, and returns the result. Called from `main` with `x=15, y=3`.

### `processArray(items)` (L13–21)
Iterates over a numeric array with a `for` loop, logging each element's index and value, accumulating a sum. Called from `main` with `[10, 20, 30, 40, 50]`.

### `fibonacci(n)` (L23–30)
Naive recursive Fibonacci implementation. Base case: `n <= 1` returns `n`. Called from `main` with `n=6` (expected result: 8).

### `main()` (L32–62)
Orchestrates the debug test:
1. Calls `calculateProduct(15, 3)` → `product = 45`
2. Calls `processArray([10,20,30,40,50])` → `arraySum = 150`
3. Calls `fibonacci(6)` → `fibResult = 8`
4. Constructs `testObject = { name: "Debug Test", value: 195, fib: 8 }` (L50–54)
5. Computes `finalResult = testObject.value + testObject.fib` = `203`
6. Returns `finalResult`

### Module-level execution (L65–66)
`main()` is invoked immediately at module load; result is logged. Script is directly runnable via `node` shebang (`#!/usr/bin/env node`, L1).

## Architectural Notes
- Pure script, no imports/dependencies, no exports — self-contained debugging fixture.
- Intentionally simple and deterministic; all values are hardcoded for predictable breakpoint inspection.
- Covers three common debugger scenarios: linear code, loops, and recursive call stacks.