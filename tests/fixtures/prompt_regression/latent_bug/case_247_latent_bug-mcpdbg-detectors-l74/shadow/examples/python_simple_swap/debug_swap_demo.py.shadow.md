# examples\python_simple_swap\debug_swap_demo.py
@source-hash: 9f508f7ef12f1eea
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:22Z

## Purpose
End-to-end demonstration script that drives a debug-mcp-server over HTTP/JSON-RPC to debug `swap_vars.py`. It creates a debug session, sets a breakpoint, starts the debugger, inspects variables before and after a step, then continues and closes the session.

## Constants
- `MCP_SERVER_URL` (L11): `"http://localhost:3000/mcp"` — target MCP server endpoint; must be running before script execution.
- `SWAP_SCRIPT_PATH` (L14): Absolute path to `swap_vars.py` resolved relative to this file's directory at module load time.

## Key Functions

### `call_mcp_tool` (L16–61)
Generic HTTP JSON-RPC 2.0 wrapper for MCP tool calls.
- Builds a `CallTool` JSON-RPC payload with `tool_name` and `arguments`.
- Injects `mcp-session-id` header when `mcp_session_id` is provided.
- Raises on HTTP errors (`raise_for_status`, L34) and on JSON-RPC-level errors (L39–40).
- Normalises the result: if `result` is a raw string it attempts `json.loads`; on parse failure returns `{"error": "result_is_unparseable_string", "raw_value": ...}`.
- Returns `(processed_tool_result, response_mcp_session_id)` — the session ID is extracted from response headers (L59).

### `run_debug_session` (L63–286)
Orchestrates a full debug workflow against `swap_vars.py` in 10 steps:
1. **Create debug session** (L75–86): Calls `create_debug_session`, captures `sessionId` and MCP HTTP session ID.
2. **Set breakpoint** (L90–101): `set_breakpoint` at line 9 of `swap_vars.py` (`a = b`). Asserts `verified` or `breakpointId` present.
3. **Start debugging** (L106–117): `start_debugging` with script path; waits 3 s for the breakpoint to be hit.
4. **Get stack trace** (L121–141): `get_stack_trace`; extracts `frame_zero` and asserts `current_line == 9`.
5. **Get scopes** (L146–163): `get_scopes` for the current frame; finds the `"Locals"` scope and its `variablesReference`.
6. **Inspect variables before step** (L168–192): `get_variables`; asserts `a == '10'` and `b == '20'`.
7. **Step over** (L197–204): `step_over`; waits 1 s.
8. **Re-fetch stack/scopes/variables after step** (L209–256): Full re-query cycle; asserts `a == '20'`.
9. **Continue execution** (L261–268): `continue_execution`; waits 2 s.
10. **Cleanup (finally block, L274–286)**: Always calls `close_debug_session` if a session was established.

Errors print to `sys.stderr` (L273); cleanup errors also print to `sys.stderr` (L286).

## Entry Point (L288–292)
Prints startup instructions, prompts user to press Enter, then calls `run_debug_session()`.

## MCP Tool Names Used (cross-file contract)
- `create_debug_session`
- `set_breakpoint`
- `start_debugging`
- `get_stack_trace`
- `get_scopes`
- `get_variables`
- `step_over`
- `continue_execution`
- `close_debug_session`

## JSON-RPC Protocol Details
- Method: `"CallTool"` (L25)
- Request IDs: `"debug-swap-demo-{tool_name}-{suffix}{uuid4()}"` (L29)
- Session tracking via `"mcp-session-id"` request/response header (L20, L59)

## Assumptions / Invariants
- `swap_vars.py` must exist at the resolved `SWAP_SCRIPT_PATH`.
- MCP server must be listening at `http://localhost:3000/mcp`.
- `swap_vars.py` line 9 must be `a = b` (1-based), with initial values `a=10`, `b=20`.
- Stack frames are returned as a list of dicts with at least `"id"` and `"line"` keys.
- Scopes list includes a dict with `"name" == "Locals"` containing `"variablesReference"`.
- Variable dicts contain `"name"`, `"value"` (as string), and `"type"` keys.