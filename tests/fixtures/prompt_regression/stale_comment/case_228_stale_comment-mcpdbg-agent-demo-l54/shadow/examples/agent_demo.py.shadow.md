# examples\agent_demo.py
@source-hash: 98d6ab5a2f9e4c59
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:44Z

## Purpose
Minimal demonstration of an LLM agent loop that drives a debug-mcp-server via JSON-RPC over HTTP. Simulates an AI agent reasoning over debugging steps with a scripted `MockLLM`, executing MCP tool calls sequentially against a running debug server.

## Key Constants
- `MCP_SERVER_URL` (L11): `"http://localhost:3000/mcp"` — hardcoded target endpoint; assumes server is already running.

## Key Functions & Classes

### `call_mcp_tool(tool_name, arguments, mcp_session_id=None)` (L14–46)
Core HTTP helper that POSTs a JSON-RPC 2.0 `CallTool` request to the MCP server.
- Injects `mcp-session-id` header if provided (L17).
- `id` field uses `f"agent-demo-{tool_name}-{uuid.uuid4()}"` pattern (L23).
- Attempts to JSON-parse string results; wraps unparseable strings in error dict (L38–44).
- Returns `(processed_tool_result, response_mcp_session_id)` tuple (L46).
- Raises `Exception` on JSON-RPC error field (L34); raises `requests.HTTPError` on HTTP errors via `raise_for_status()` (L28).

### `MockLLM` (L49–94)
Scripted mock of an LLM agent that follows a fixed `plan` list.

**`__init__`** (L50–64):
- `self.plan` (L52–61): Hardcoded sequence of tool calls:
  1. `create_debug_session` (language=python)
  2. `set_breakpoint` at `examples/python_simple_swap/swap_vars.py` line 9
  3. `start_debugging` same script
  4. `get_stack_trace` (sessionId filled dynamically)
  5. `close_debug_session` (sessionId filled dynamically)
- `self.debug_session_id` (L63): Stores debug session ID from `create_debug_session` result.
- `self.mcp_http_session_id` (L64): Stores HTTP-level MCP session ID from response headers.

**`think(observation)` → `(tool_name, tool_args) | None`** (L66–94):
- Appends observation to `self.history` (L68).
- Returns `None` when plan is exhausted (L70–72).
- Auto-injects `sessionId` into args for non-session-management tools (L79–81).
- Resolves relative `file` paths to absolute for `set_breakpoint` (L84–89).
- Advances `self.current_step` (L92).

### `agent_loop()` (L96–145)
Main execution loop, up to 10 iterations (L100).
- Calls `llm.think(observation)` → obtains `(tool_name, tool_args)` or `None` to break (L105–108).
- Calls `call_mcp_tool(...)` and updates `llm.mcp_http_session_id` from response (L113–117).
- Extracts and stores `sessionId` from `create_debug_session` result (L122–124).
- On `start_debugging` success, sleeps 3 seconds to simulate waiting for breakpoint (L126–129).
- On exception, feeds error dict back as observation (L132–134).
- **Post-loop cleanup** (L139–145): Attempts `close_debug_session` if session appears still open. The condition logic on L139–140 has a subtle off-by-one / edge case risk (see findings).

## Entry Point (L148–158)
- Validates `examples/python_simple_swap/swap_vars.py` exists before starting (L150–154).
- Prints server URL reminder and prompts for Enter key before running `agent_loop()`.

## Architecture / Patterns
- Agent loop is ReAct-style: observe → think → act → observe.
- `MockLLM` encodes a fixed plan rather than real LLM inference — purely for demo purposes.
- MCP session persistence uses both HTTP response header `mcp-session-id` and a JSON-RPC-level `sessionId` argument (two separate session concepts).
- No retry logic; errors are fed back into the observation for the next LLM step.

## Dependencies
- `requests` — HTTP POST to MCP server.
- `json`, `uuid`, `time`, `os`, `sys` — stdlib utilities.