# tests\test-utils\fixtures\python\debugpy_server.py
@source-hash: 39e56092a7039cff
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:47Z

## Debugpy Server Fixture (`debugpy_server.py`)

A standalone test fixture script that launches a `debugpy` DAP (Debug Adapter Protocol) server in listening mode. Intended to be run as a subprocess target during MCP server integration tests, where the MCP server acts as the DAP *client* connecting to this process.

### Architecture Role
This script is the "debuggee" side of the DAP connection: it starts `debugpy.listen()` and optionally blocks until a client attaches, then runs debuggable code (Fibonacci) with a programmatic breakpoint.

---

### Module-Level Setup (L13–18)
- Attempts `import debugpy`; prints version on success, prints error and calls `sys.exit(1)` on `ImportError`. This guard ensures the script fails fast if debugpy is unavailable.

### Constants (L21–22)
- `DEFAULT_HOST = "127.0.0.1"` — loopback-only binding
- `DEFAULT_PORT = 5679` — chosen to avoid conflict with the default debugpy port (5678)

---

### Key Functions

#### `start_debugpy_server(host, port, wait_for_client)` (L24–52)
- Calls `debugpy.listen((host, port))` to open the DAP listener socket.
- If `wait_for_client=True` (default), blocks on `debugpy.wait_for_client()` until a DAP client attaches.
- Returns `True` on success, `False` on any exception.

#### `fibonacci(n)` (L54–69)
- Iterative Fibonacci computation; serves as the debuggable workload.
- Prints intermediate state, making it easy to observe variable values via a debugger.

#### `run_fibonacci_test()` (L71–81)
- Calls `debugpy.breakpoint()` (L74) to set a programmatic breakpoint before executing `fibonacci(10)`.
- Returns `True` unconditionally after the test run.

---

### `__main__` Entry Point (L83–109)
CLI arguments parsed via `argparse`:
| Flag | Default | Effect |
|------|---------|--------|
| `--host` | `127.0.0.1` | Bind host |
| `--port` | `5679` | Bind port |
| `--no-wait` | False | Skip `wait_for_client` |
| `--run-test` | False | Run fibonacci test with breakpoint |

**Execution flow:**
1. Start server → exit with code 1 on failure (L92–94).
2. If `--run-test`: call `run_fibonacci_test()` (L96–97).
3. Otherwise: spin in `while True: time.sleep(1)` loop until `KeyboardInterrupt` (L99–105) — "server mode".
4. In both branches, wait 5 seconds then exit (L107–110).

---

### Dependencies
- `debugpy` — third-party; must be installed in the test environment
- `sys`, `time`, `argparse` — stdlib only