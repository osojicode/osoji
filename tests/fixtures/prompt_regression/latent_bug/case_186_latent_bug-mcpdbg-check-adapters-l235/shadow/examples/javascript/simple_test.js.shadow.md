# examples\javascript\simple_test.js
@source-hash: 1d758932fc4c3cb6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:59Z

## Overview

Minimal JavaScript smoke-test script (`examples/javascript/simple_test.js`) that mirrors the Python sample for MCP debugger end-to-end validation. Exercises breakpoint placement, variable inspection, and stepping behavior in the JavaScript debug adapter.

## Key Symbols

- **`main` (L8-16)** — Exported entry-point function. Declares two local variables `a=1`, `b=2`, logs their initial state (L11), performs an in-place destructuring swap `[a, b] = [b, a]` (L14), then logs the result (L15). The comment on L13 explicitly marks L14 as the intended breakpoint target so variables are readable in their pre-swap state.

## Execution Flow

1. Module loads → `main()` is called immediately at L18 (top-level call, not guarded).
2. `main()` runs the swap scenario end-to-end.

## Debugger Contract

- **Breakpoint target**: L14 (`[a, b] = [b, a]`) — variables `a` and `b` hold initial values `1` and `2` at this point.
- **Expected pre-swap log**: `Before swap: a=1, b=2`
- **Expected post-swap log**: `After swap: a=2, b=1`

## Dependencies

No external or internal imports. Uses only Node.js built-in `console.log`.

## Notes

- Uses ES module `export` syntax (L8), making `main` importable by test harnesses without re-executing the top-level call (though L18 does invoke it unconditionally on load).
- The shebang `#!/usr/bin/env node` (L1) allows direct CLI execution.