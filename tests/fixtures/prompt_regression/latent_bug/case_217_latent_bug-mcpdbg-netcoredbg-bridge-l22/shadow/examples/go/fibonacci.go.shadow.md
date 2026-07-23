# examples\go\fibonacci.go
@source-hash: 7f809679531cb9f3
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:51Z

## Overview
A standalone Go entry-point (`package main`) that demonstrates recursive Fibonacci number calculation. Prints the sequence for indices 0–10, then computes a single value at index 15.

## Key Symbols

### `fibonacci` (L8–13)
Recursive function computing the nth Fibonacci number using the classic definition:
- **Base case:** `n <= 1` returns `n` directly (handles both 0 and 1).
- **Recursive case:** `fibonacci(n-1) + fibonacci(n-2)`.
- **Complexity:** O(2ⁿ) time — no memoization. Practical upper bound is low tens before noticeable slowdown.
- Accepts and returns plain `int` (platform-dependent width on Go; 64-bit on most modern targets).

### `main` (L15–29)
Program entry point:
1. Prints a header banner (L16–17).
2. Loop `i = 0..10` (inclusive): calls `fibonacci(i)` and prints each result via `fmt.Printf` (L20–23).
3. Computes `fibonacci(15)` explicitly and prints it (L26–28).

## Dependencies
- `fmt` (stdlib): `Println` and `Printf` for console output only.
- No external packages or project-internal imports.

## Architectural Notes
- Pure example/demo file — no library API surface; all logic is `package main`.
- `fibonacci` is unexported (lowercase); it is only used within `main`.
- No error handling required (integer arithmetic, no I/O errors).
- The separator string at L17 (`"=============================="`) is 30 `=` characters while the header at L16 is 29 characters — minor cosmetic mismatch but no functional impact.