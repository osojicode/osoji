# examples\javascript\mcp_target.js
@source-hash: 20db91ba517632f7
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:00Z

## Purpose
A self-contained JavaScript debugging target script used to exercise MCP (Model Context Protocol) JavaScript debugging features. Not a library — intended to be run directly and paused/inspected by a debugger.

## Key Symbols

### `testData` (L13-17) — module-level constant
Hardcoded object with `name`, `version`, and `features` fields. Used as sample structured data logged in `main()` to verify object inspection in the debugger.

### `deepFunction(level)` (L20-27)
Recursive function that decrements `level` until 0, then returns the string `"Bottom of stack"`. Designed to produce a multi-frame call stack (depth = `level + 1`) for stack-trace testing. Called with `deepFunction(3)` at L48, yielding 4 frames.

### `testVariables()` (L30-39)
Declares several local variables of varying types (`number`, `string`, `array`, `object`) to provide targets for variable inspection and expression evaluation in a debugger. Returns `number * 2` (i.e., `84`). The `string`, `array`, and `object` locals are declared but never read after assignment — they exist solely as debugger inspection targets.

### `main()` (L42-57) — async entry point
Orchestrates two labeled test sections:
- **Test 1** (L47-49): Calls `deepFunction(3)` and logs result.
- **Test 2** (L52-54): Calls `testVariables()` and logs result.

### Top-level invocation (L60-63)
Calls `main()` and attaches a `.catch` handler that logs the error and calls `process.exit(1)`.

## Architectural Notes
- File is a pure **entry/script** — no exports, no imports, no external dependencies beyond Node.js builtins (`console`, `process`).
- Designed for manual breakpoint placement at any line; the async `main` wrapper is present for style/convention, not for actual async operations.
- `testVariables()` intentionally declares unused locals (`string`, `array`, `object`) as debugger inspection bait — these are not dead code in the conventional sense but rather intentional test fixtures.
