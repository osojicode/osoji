# examples\agent_demo.py
@source-hash: 98d6ab5a2f9e4c59
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:01Z

## Overview
Minimal demonstration of an LLM agent loop that interacts with a `debug-mcp-server` via JSON-RPC over HTTP. Simulates an AI agent planning and executing a debugging workflow against a target Python script (`swap_vars.py`) using a mock LLM with a pre-scripted plan.

## Key Symbols

### `MCP_SERVER_URL` (L11)
Constant pointing to `http://localhost:3000/mcp`. Server must be running before the demo starts.

### `call_mcp_tool(tool_name, arguments, mcp_session_id=None)` (L14–46)
Low-level MCP transport helper. Sends a JSON-RPC 2.0 `POST` to `MCP_SERVER_URL` with method `"CallTool"`. 
- Sets `mcp-session-id` header if a session ID is provided.
- Unique request IDs: `agent-demo-{tool_name}-{uuid4}`.
- Response handling: raises on HTTP errors, raises `Exception` on JSON-RPC `"error"` field, attempts JSON-parse of string results.
- Returns `(processed_tool_result, new_mcp_session_id_from_response_header)`.

### `MockLLM` (L49–94)
Simulates an LLM agent with a fixed execution plan. Not a real LLM; deterministically steps through `self.plan`.

**`__init__`** (L50–64): Initializes a 5-step plan:
1. `create_debug_session` — language=python
2. `set_breakpoint` — file=`examples/python_simple_swap/swap_vars.py` (line 9)
3. `start_debugging` — same script
4. `get_stack_trace` — no initial args (sessionId injected dynamically)
5. `close_debug_session` — no initial args (sessionId injected dynamically)

Tracks: `history`, `current_step`, `debug_session_id`, `mcp_http_session_id`.

**`think(observation)` → `tuple[str, dict] | None`** (L66–94):
- Appends observation to `self.history`.
- Returns `None` when plan is exhausted.
- Dynamically injects `sessionId` into args for any tool except `create_debug_session` / `list_debug_sessions` if `self.debug_session_id` is set.
- Resolves relative file paths for `set_breakpoint` via `os.path.abspath`.

### `agent_loop()` (L96–145)
Main agent execution loop. Runs up to 10 iterations:
1. Calls `llm.think(observation)` to get `(tool_name, tool_args)`.
2. Calls `call_mcp_tool(...)` with current MCP HTTP session.
3. Propagates `mcp-session-id` header from responses back to `llm.mcp_http_session_id`.
4. After `create_debug_session`: stores returned `sessionId` in `llm.debug_session_id` (L123).
5. After `start_debugging` success: sleeps 3 seconds to simulate waiting for breakpoint hit (L128).
6. On exception: feeds error dict back as observation; continues loop.
7. **Cleanup (L139–145)**: After loop, if a debug session is open and `close_debug_session` wasn't the last executed step, calls `close_debug_session` explicitly.

### `__main__` block (L148–159)
- Validates that `examples/python_simple_swap/swap_vars.py` exists; exits with code 1 if not.
- Prints server URL, target script path.
- Waits for Enter keypress before starting `agent_loop()`.

## Architecture Notes
- **JSON-RPC 2.0** transport: method is `"CallTool"`, params contain `name` and `arguments`.
- **Stateful HTTP session**: `mcp-session-id` header is propagated across calls for server-side session continuity.
- **No real LLM**: `MockLLM.think` is a simple plan step iterator — this is a scripted demo, not adaptive AI.
- The cleanup logic at L139–140 has a subtle edge-case bug (see Findings).
- Relative-to-CWD path resolution: file paths in the plan use `os.path.abspath` at plan-creation time (L56–57), so the demo must be run from the project root.

## Dependencies
- `requests`: HTTP POST to MCP server
- `json`, `uuid`, `time`, `os`, `sys`: stdlib utilities