# tests\test-utils\fixtures\python\debug_test_simple.py
@source-hash: 5fe5e778725e1905
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:00Z

## Overview

A minimal Python fixture script used as a debug test target. It exists solely to provide a long-running, inspectable process (via `time.sleep(60)`) that a debugger or test harness can attach to, step through, and observe. Not meant to be imported — executed directly as a script.

## Execution Flow

1. **Module-level (L6–7):** Prints Python version and a startup banner immediately on execution.
2. **`sample_function` (L10–14):** Defines a trivially simple arithmetic function (`a=5`, `b=10`, `c=a+b`) with a print — intended as a breakpoint/step-through target for debugger tests.
3. **Module-level (L17–20):** Calls `sample_function()`, then sleeps for 60 seconds (L20), providing a window for debugger attachment or observation.
4. **Module-level (L21):** Prints an exit message after the sleep completes.

## Key Design Points

- The 60-second `time.sleep(60)` (L20) is the architectural centerpiece: it keeps the process alive long enough for test infrastructure to attach a debugger, send signals, or inspect state.
- `sample_function` (L10–14) is the intended debug target — its local variables (`a`, `b`, `c`) are simple and predictable, making it ideal for verifying variable inspection in debugger tests.
- No imports beyond stdlib (`sys`, `time`); no classes, no external dependencies.