# examples\python\fibonacci.py
@source-hash: bae9881f2c6491a0
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:55Z


## Overview
A self-contained example/test script demonstrating two Fibonacci implementations (recursive and iterative), plus an intentionally introduced bug — designed for use as a debugging target with the Debug MCP Server.

## Key Symbols

### `fibonacci_recursive(n)` (L9–16)
Pure recursive Fibonacci. Base cases: `n <= 0` → 0, `n == 1` → 1. Returns `fib(n-1) + fib(n-2)` for all other values. No memoization; exponential time complexity.

### `fibonacci_iterative(n)` (L19–28)
Iterative Fibonacci using two-variable rolling update (`a, b = b, a+b`). Base case: `n <= 0` → 0. Runs in O(n) time.

### `main()` (L31–50)
Demonstrates both implementations for `n = 10`. Intentionally computes `fibonacci_iterative(9) + 1` as `buggy_value` (L46) — a deliberate off-by-one bug for debugging exercises. Prints a diagnostic message if `buggy_value` mismatches `fibonacci_iterative(10)`.

## Entry Point
Standard `if __name__ == "__main__": main()` guard at L53–54.

## Notable Design Decisions
- The bug at L46 is **intentional**: the comment explicitly states "This should be +0 not +1". This is a debugging exercise fixture, not a real defect to fix.
- Both implementations are correct; only `main()` introduces erroneous behavior.
- No external dependencies.
