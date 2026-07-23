# examples\go\fibonacci\main.go
@source-hash: 7b83cd29c5a3c61c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:57Z

## Overview
Entry point for a Fibonacci calculator example demonstrating three algorithmic approaches: recursive, iterative, and memoized. Computes and benchmarks `fibonacci(10)` for each strategy, then prints the full sequence F(0) to F(10).

## Key Functions

### `main` (L8-40)
Orchestrates three timed Fibonacci computations for `n=10` and prints the full sequence. Uses `time.Now()` / `time.Since()` for naive wall-clock benchmarking. Sequence print loop (L37-39) calls `fibonacciIterative` redundantly for each index.

### `fibonacciRecursive(n int) int` (L43-48)
Classic recursive implementation. Base case: `n <= 1` returns `n`. Exponential time complexity O(2^n). Comment at L42 accurately notes it is slow for large numbers.

### `fibonacciIterative(n int) int` (L51-66)
Space-efficient O(n) iterative implementation using two rolling variables (`prev`, `curr`). Base case: `n <= 1` returns `n`. Returns `curr` after loop.

### `fibonacciMemoized(n int, memo map[int]int) int` (L69-84)
Top-down recursive implementation with caller-supplied `map[int]int` cache. Base case: `n <= 1` returns `n`. Cache is checked before recursion (L75-77) and populated after (L80-81). Cache is not pre-seeded with base cases; they are handled by the base case guard.

## Dependencies
- `fmt`: Console output only.
- `time`: Wall-clock timing via `time.Now()` / `time.Since()`.

## Architectural Notes
- All three functions share the same base case contract: input `n <= 1` returns `n` directly, correctly handling both F(0)=0 and F(1)=1.
- The memoized function requires the caller to allocate and pass the memo map (L29); no global or closure-based cache is used.
- This is a self-contained example/demo binary; no exported symbols.