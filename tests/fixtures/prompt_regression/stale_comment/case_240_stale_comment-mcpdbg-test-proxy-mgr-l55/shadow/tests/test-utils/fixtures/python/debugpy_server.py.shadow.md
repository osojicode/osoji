# tests\test-utils\fixtures\python\debugpy_server.py
@source-hash: 39e56092a7039cff
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:31Z

## Purpose
A standalone Python script/fixture that starts a `debugpy` server in listening mode, intended for testing an MCP server's DAP (Debug Adapter Protocol) client integration. The script acts as the debug target that a DAP client (e.g., MCP server) connects to.

## Architecture Role
Entry-point script runnable directly via `python debugpy_server.py [options]`. Demonstrates the correct debugpy server pattern: this process calls `debugpy.listen()`, and an external client (the MCP server under test) connects to it as a DAP client.

## Key Symbols

### Constants (L21–22)
- `DEFAULT_HOST = "127.0.0.1"` — loopback address for local testing
- `DEFAULT_PORT = 5679` — chosen to avoid conflicts with standard debugpy port (5678)

### `start_debugpy_server(host, port, wait_for_client)` (L24–52)
- Calls `debugpy.listen((host, port))` to bind the debug server
- Optionally calls `debugpy.wait_for_client()` to block until the DAP client connects
- Returns `True` on success, `False` on exception
- Default: waits for client (`wait_for_client=True`)

### `fibonacci(n)` (L54–69)
- Simple iterative Fibonacci implementation
- Serves as a debuggable workload — exercises variable inspection, stepping
- Prints progress/result; no side effects beyond stdout

### `run_fibonacci_test()` (L71–81)
- Calls `debugpy.breakpoint()` programmatically (L74) to trigger a DAP breakpoint event
- Invokes `fibonacci(10)` as the workload under the breakpoint
- Returns `True` unconditionally

### `__main__` block (L83–109)
- Parses CLI args: `--host`, `--port`, `--no-wait`, `--run-test`
- Calls `start_debugpy_server(...)` and exits with code 1 on failure
- If `--run-test`: runs `run_fibonacci_test()` then sleeps 5 s before exiting
- Otherwise: loops indefinitely (`while True: time.sleep(1)`) until `KeyboardInterrupt`, then sleeps 5 s before exiting

## CLI Interface
| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `5679` | Bind port |
| `--no-wait` | off | Skip `wait_for_client()` |
| `--run-test` | off | Execute fibonacci breakpoint test |

## Key Dependencies
- `debugpy` — third-party; import failure causes immediate `sys.exit(1)` (L13–18)
- `argparse`, `sys`, `time` — stdlib

## Notable Pattern
The 5-second sleep at L109 executes **after both branches** (`--run-test` and server-loop paths), allowing time for the DAP client to inspect state after the workload completes before the process exits.

## Constraints / Invariants
- Must be run as `__main__` to exercise the argument-parsing entry point; importing as a module exposes `start_debugpy_server`, `fibonacci`, and `run_fibonacci_test` but does not auto-start the server
- `debugpy.breakpoint()` in `run_fibonacci_test` will hang if no DAP client is connected and `wait_for_client` was skipped
