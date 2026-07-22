# examples\ruby\long_running.rb
@source-hash: 27268de8898f1d18
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:56Z

## Purpose
A minimal Ruby script designed as a live attach target for `rdbg` remote debugging sessions. Runs an infinite counter loop, printing a tick message and squared value every second — useful for demonstrating or testing the `attach_to_process` MCP tool.

## Execution Flow
1. **Initialization (L6-7):** Two mutable variables are set: `counter = 0` and `message = 'tick'`.
2. **Infinite loop (L9-14):** Each iteration:
   - Increments `counter` by 1 (L10)
   - Computes `squared = counter * counter` (L11)
   - Prints `"tick N (squared: N²)"` to stdout (L12)
   - Sleeps 1 second (L13)

## Usage
Launch as an rdbg remote debug target:
```
rdbg --open --host 127.0.0.1 --port 12345 long_running.rb
```
Then attach using the `attach_to_process` MCP tool.

## Key Variables
- `counter` (L6): Integer, incremented each tick; primary inspection target during debugging.
- `message` (L7): String `'tick'`; prefix for printed output — can be mutated via debugger to observe live variable changes.
- `squared` (L11): Ephemeral local computed each iteration; demonstrates derived-value inspection.

## Architectural Notes
- No classes, methods, or requires — fully flat procedural script.
- Intentionally simple so a debugger can set breakpoints, inspect locals, and mutate `counter` or `message` mid-loop without side effects.
- The loop is truly infinite (`loop do`) with no exit condition; must be terminated externally (Ctrl-C, debugger quit, or process kill).