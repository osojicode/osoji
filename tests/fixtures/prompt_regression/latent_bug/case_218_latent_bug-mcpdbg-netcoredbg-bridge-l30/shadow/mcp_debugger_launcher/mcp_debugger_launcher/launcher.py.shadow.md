# mcp_debugger_launcher\mcp_debugger_launcher\launcher.py
@source-hash: cc9c327f51e4ca14
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:27Z

## Core Launcher Logic for debug-mcp-server

Provides the `DebugMCPLauncher` class (L11-151) that wraps subprocess management for launching the `@debugmcp/mcp-debugger` package via either `npx` or Docker. Handles signal registration, real-time output streaming, graceful shutdown, and process cleanup.

---

### Class: `DebugMCPLauncher` (L11-151)

**Class-level constants:**
- `NPM_PACKAGE = "@debugmcp/mcp-debugger"` (L14) — npm package name passed to `npx`
- `DOCKER_IMAGE = "debugmcp/mcp-debugger:latest"` (L15) — Docker image reference, including auto-pull on first use
- `DEFAULT_SSE_PORT = 3001` (L16) — fallback port for SSE mode in Docker launches

**Instance state:**
- `self.verbose` (bool) — gates non-error log output
- `self.process` (Optional[subprocess.Popen]) — holds the active child process; reset to `None` on cleanup

---

### Key Methods

#### `__init__` (L18-20)
Parameters: `verbose: bool = False`. Initialises `self.process = None`.

#### `log` (L22-26)
Conditional logging: prints to `stdout` normally, `stderr` on error. Always emits when `error=True` regardless of `verbose`.

#### `launch_with_npx` (L28-71)
Builds command: `npx @debugmcp/mcp-debugger <mode> [--port <port>]`. Registers `SIGINT`/`SIGTERM` handlers, spawns subprocess with merged stdout/stderr (`stderr=subprocess.STDOUT`), streams output line-by-line. Returns child process exit code, or `1` on `FileNotFoundError`, or `0` on `KeyboardInterrupt`. Always calls `_cleanup()` in `finally`.

#### `launch_with_docker` (L73-132)
Builds `docker run -it --rm` command with optional `-p` port mapping for SSE mode. **Pre-flight check** (L94-102): runs `docker images -q` to detect local image; if absent, auto-pulls via `docker pull`. Then spawns container and streams output identically to `launch_with_npx`. Same return-code and cleanup contract.

#### `_signal_handler` (L134-141)
POSIX signal callback for `SIGINT`/`SIGTERM`. Calls `self.process.terminate()`; if process does not exit within 5 s (`TimeoutExpired`), escalates to `self.process.kill()`.

#### `_cleanup` (L143-151)
Idempotent teardown: checks `poll() is None` before terminating, waits up to 5 s, kills if needed, then sets `self.process = None`.

---

### Architectural Notes

- **stdout/stderr merge**: Both `launch_with_npx` and `launch_with_docker` use `stderr=subprocess.STDOUT`, so all child output is read from a single pipe. This prevents stderr from being silently discarded but means callers cannot distinguish the two streams.
- **SSE port inconsistency (potential bug)**: In `launch_with_docker` (L78-84), when `mode == "sse"` the Docker `-p` flag always uses `actual_port` (defaulting to 3001 if `port` is `None`), but the `--port` flag to the container (L83-84) is only appended `if port` — so when `port=None`, the container receives no `--port` argument while Docker maps port 3001. If the container's internal default differs from 3001 this will silently misconfigure the port mapping.
- **Signal handler registration on every call**: `signal.signal()` is called inside both launch methods, meaning repeated calls overwrite the prior handler.
- **No Windows SIGTERM**: `signal.SIGTERM` is not available on Windows; this code will raise `AttributeError` on non-POSIX platforms.
- **`subprocess.CalledProcessError` unreachable in `launch_with_npx`**: `subprocess.Popen` itself does not raise `CalledProcessError`; only `subprocess.run(..., check=True)` does. The `except subprocess.CalledProcessError` branch (L64-66) in `launch_with_npx` is dead code for the `Popen` path. (The Docker method does use `check=True` for the pull step, but catches it in the same handler.)
