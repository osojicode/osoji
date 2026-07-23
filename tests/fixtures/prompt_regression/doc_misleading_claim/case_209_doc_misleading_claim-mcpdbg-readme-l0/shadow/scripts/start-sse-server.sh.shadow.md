# scripts\start-sse-server.sh
@source-hash: 1361f5a0b9ddab49
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:56Z

## Purpose
Bash launcher script that validates runtime dependencies and starts the Debug MCP Server in SSE (Server-Sent Events) mode on port 3001.

## Execution Flow

1. **Dependency Checks (L9–35):**
   - Verifies `node` is in PATH (L9–12); exits with code 1 on failure.
   - Verifies either `python` or `python3` is in PATH (L16–19); exits with code 1 on failure.
   - Resolves the Python command (`python3` preferred over `python`) into `PYTHON_CMD` variable (L22–26).
   - Verifies `debugpy` Python module is importable via `$PYTHON_CMD -c "import debugpy"` (L30–34); exits with code 1 on failure, printing pip install hint.

2. **Server Startup (L48–49):**
   - Creates `logs/` directory if it doesn't exist (L48).
   - Launches `node dist/index.js sse --port 3001 --log-level debug --log-file logs/debug-mcp-server.log` (L49); runs in foreground (Ctrl+C to stop).

## Key Configuration
- **Endpoint:** `http://localhost:3001/sse` (L41)
- **Transport mode:** `sse` passed as positional argument to the Node.js entry point (L49)
- **Port:** `3001` (L49)
- **Log level:** `debug` (L49)
- **Log file:** `logs/debug-mcp-server.log` (L49)
- **Entry point:** `dist/index.js` — expects pre-built compiled output (L49)

## Dependencies
- `node` — must be in PATH; runs the compiled TypeScript/JavaScript server
- `python` or `python3` — must be in PATH; used for `debugpy` check
- `debugpy` Python package — must be importable; likely used by the MCP server for Python debug protocol support
- `dist/index.js` — compiled server artifact; script does NOT build it (no `npm run build` step)

## Notable Patterns / Constraints
- Script does **not** build the project before starting; assumes `dist/index.js` already exists.
- `python3` is preferred over `python` when both are available (L22–26).
- All three dependency checks are hard exits (exit code 1); no partial-start fallback.
- Log directory is created silently (`2>/dev/null`) to avoid noise if it already exists (L48).
- The Node.js process replaces the shell (no `exec`); Ctrl+C terminates node directly since it's the last foreground command.