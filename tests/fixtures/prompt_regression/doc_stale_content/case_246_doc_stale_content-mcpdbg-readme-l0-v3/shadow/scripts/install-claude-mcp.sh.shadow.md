# scripts\install-claude-mcp.sh
@source-hash: faa2787c22ac1c87
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:33Z

## Purpose
Bash installation script that automates the registration of `mcp-debugger` as an MCP server within Claude Code's CLI configuration. Handles build, registration, and verification in a single invocation.

## Execution Flow (top-level, no functions defined)

1. **Environment setup (L7-8):** Resolves `SCRIPT_DIR` (directory of this script) and `PROJECT_DIR` (parent of `scripts/`), e.g. repo root.
2. **Claude CLI detection (L14-19):** Uses `command -v claude` to locate the Claude CLI. Exits with code 1 if not found.
3. **Build step (L22-25):** `cd`s to `PROJECT_DIR`, runs `pnpm install --frozen-lockfile` then `npm run build`. Produces `dist/index.js`.
4. **Deregistration (L28-29):** Removes any pre-existing `mcp-debugger` entry via `claude mcp remove mcp-debugger`; errors suppressed (`2>/dev/null || true`).
5. **Registration (L32-34):** Calls `claude mcp add-json mcp-debugger` with a JSON payload configuring a `stdio` transport, command `node`, and args `["<PROJECT_DIR>/dist/index.js", "stdio"]`.
6. **Verification (L37-70):** Waits 1 second, then checks `claude mcp list` for the string `mcp-debugger.*✓ Connected`. Prints success instructions or warning with next steps accordingly.

## Key Variables
- `SCRIPT_DIR` (L7): Absolute path to `scripts/` directory.
- `PROJECT_DIR` (L8): Repo root (parent of `scripts/`).
- `CLAUDE_CLI` (L14): Resolved path to `claude` binary.

## MCP Server Registration Payload (L33-34)
```json
{
  "type": "stdio",
  "command": "node",
  "args": ["<PROJECT_DIR>/dist/index.js", "stdio"],
  "env": {}
}
```
Entry point: `dist/index.js` with argument `stdio`.

## Tool Prefix in Claude Code
Registered tools are prefixed `mcp__mcp-debugger__` (L53). Documented example tools: `create_debug_session`, `set_breakpoint`, `start_debugging` (L56-58).

## Supported Languages (informational, L43-49)
Python (debugpy), JavaScript/TypeScript (Node 22+), Rust, Go (Delve), Java (JDK 11+), .NET/C# (netcoredbg), Mock.

## Dependencies
- `bash`, `pnpm`, `npm`, `node`, `claude` CLI must all be on `PATH`.
- `set -e` (L5): Any command failure aborts the script immediately (except explicit `|| true` guards).

## Notable Patterns
- Mixed package managers: `pnpm install` for dependencies, `npm run build` for the build step. This is intentional but may cause confusion.
- Verification uses a regex grep (`mcp-debugger.*✓ Connected`) against CLI list output; fragile if Claude CLI output format changes.
- `sleep 1` (L38) added before verification to allow Claude CLI state to settle — heuristic delay.