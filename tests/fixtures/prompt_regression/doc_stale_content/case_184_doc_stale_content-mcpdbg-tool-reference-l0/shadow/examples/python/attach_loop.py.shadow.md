# examples\python\attach_loop.py
@source-hash: 69cb092bda6a4335
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:50Z

## Purpose
A minimal long-running target process designed for `attach_to_process` smoke tests. It signals readiness via stdout, then loops indefinitely calling a trivial arithmetic function with a 0.5-second sleep between iterations.

## Key Elements

- **`compute(a, b)` (L6–8):** Adds two numbers and returns the result. Exists solely to provide a named, inspectable call frame for debugger attach tests.
- **Ready signal (L11):** Prints `"ATTACH_LOOP_READY"` with `flush=True` so the parent test process can reliably detect when this script is ready to be attached to (avoids buffering delays).
- **Infinite loop (L12–14):** Calls `compute(42, 58)` and sleeps 0.5s per iteration. Keeps the process alive and executing so a debugger can attach, set breakpoints, and inspect state.

## Architecture & Usage
This script is intended to be launched as a **subprocess** by a test harness. The parent process reads stdout and waits for the `"ATTACH_LOOP_READY"` sentinel before issuing a debugger attach command. The 0.5s sleep prevents CPU spinning while keeping the process responsive for attach latency testing.