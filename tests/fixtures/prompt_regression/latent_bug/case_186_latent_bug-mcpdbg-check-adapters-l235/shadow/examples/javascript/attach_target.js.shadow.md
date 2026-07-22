# examples\javascript\attach_target.js
@source-hash: 80421f1f50ae317f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:46Z

## Purpose
Long-running Node.js process designed to serve as a debugger attach target for the JavaScript attach smoke test (issue #124). Runs indefinitely via `setInterval`, logging a tick message every 10 iterations, until externally killed.

## Usage
Started via: `node --inspect=127.0.0.1:<port> attach_target.js`

The `--inspect` flag enables the V8 inspector protocol, allowing a debugger to attach at any time during execution.

## Key Elements

- **`counter`** (L7): Module-level mutable integer, incremented on every tick. Tracks total number of ticks elapsed.
- **`message`** (L8): Constant string `'tick'` used as the log prefix.
- **`tick()`** (L10–15): Called every 100ms by `setInterval`. Increments `counter`; logs `"tick <N>"` to stdout whenever `counter` is divisible by 10 (i.e., every ~1 second).
- **`setInterval(tick, 100)`** (L17): Schedules `tick` to run every 100ms, keeping the Node.js event loop alive indefinitely.
- **Startup log** (L18): Emits `'attach target started'` immediately to stdout to signal readiness.

## Architectural Notes
- Entirely self-contained; no imports or dependencies.
- The process never exits on its own — must be killed externally (e.g., by the test harness after attach verification).
- The 100ms interval with logging every 10th tick provides a visible heartbeat (~1 log/sec) useful for confirming the process is alive during testing.