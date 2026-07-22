# examples\debugging\test-debug-python.py
@source-hash: 034c3624d6f52339
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:53Z

## Purpose
A minimal Python script designed as a debugging target for the MCP debugger. Exercises common debugging scenarios: simple arithmetic, loop iteration, and variable inspection. No external dependencies.

## Key Symbols

- **`calculate_sum(a, b)` (L4–8):** Adds two numbers, prints the operation, returns the result.
- **`process_list(items)` (L10–16):** Iterates over a list with `enumerate`, accumulates a running total via `+=`, prints each item, returns the total.
- **`main()` (L18–36):** Orchestrates the test scenarios:
  - L23–25: Calls `calculate_sum(10, 20)` → `sum_result = 30`
  - L28–29: Calls `process_list([1,2,3,4,5])` → `list_sum = 15`
  - L32–33: Combines results into `final_result = 45`
  - L35: Prints summary message
  - L36: Returns `final_result`
- **Module entry (L38–40):** Standard `if __name__ == "__main__"` guard; calls `main()` and prints final result.

## Debugging Value
The script is structured to provide multiple interesting breakpoint locations:
- Inside the loop in `process_list` (L13–15) for step-through and variable watch.
- After each function call in `main` (L25, L29) for return value inspection.
- Final computation (L33) for arithmetic verification.

## Architectural Notes
- No imports; fully self-contained.
- Pure functions with no side effects beyond `print` calls.
- Straightforward control flow makes it ideal for validating debugger step/continue/variable-inspect features.