# scripts\install-claude-mcp.sh
@source-hash: faa2787c22ac1c87
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:04Z

## Purpose
Bash installation script that automates registering `mcp-debugger` as an MCP server in Claude Code (the Claude CLI). Handles build, config removal/add, and verification in one invocation.

## Execution Flow

1. **Environment setup (L7-8):** Derives `SCRIPT_DIR` (absolute path of this script) and `PROJECT_DIR` (parent directory — the repo root).
2. **Claude CLI detection (L14-19):** Checks `$PATH` for the `claude` binary; exits with error if not found.
3. **Project build (L22-25):** Runs `pnpm install --frozen-lockfile` then `npm run build` from `$PROJECT_DIR`.
4. **Config cleanup (L28-29):** Runs `claude mcp remove mcp-debugger`; errors suppressed (`2>/dev/null || true`).
5. **MCP server registration (L32-34):** Calls `claude mcp add-json mcp-debugger` with a JSON payload configuring a `stdio` transport, `node` command, and entry point `$PROJECT_DIR/dist/index.js` with `"stdio"` argument.
6. **Verification (L37-71):** Waits 1 second, then greps `claude mcp list` output for `"mcp-debugger.*✓ Connected"`. Prints success guidance (L40-60) or a warning with restart instructions (L62-71).

## Key Details

- **Entry point registered:** `node $PROJECT_DIR/dist/index.js stdio` — requires a successful build producing `dist/index.js`.
- **Transport type:** `stdio` (inline JSON, L34).
- **MCP tool prefix advertised:** `mcp__mcp-debugger__` (L53).
- **Supported languages listed (L43-49):** Python (debugpy), JS/TS (Node 22+), Rust, Go (Delve), Java (JDK 11+), .NET/C# (netcoredbg), Mock.
- **`set -e` (L5):** Any unexpected command failure aborts the script immediately; the `|| true` on L29 is intentional to tolerate missing prior config.
- **No sudo / system-wide changes:** All operations are user-scoped via the Claude CLI.

## Dependencies
- `bash`, `command`, `grep`, `sleep` — standard POSIX utilities.
- `pnpm` — package manager for dependency installation.
- `npm` — used to run the `build` script (may delegate to the same toolchain).
- `claude` CLI — Claude Code CLI tool; must be on `$PATH`.

## Referenced Files / Docs
- `$PROJECT_DIR/dist/index.js` — compiled server entry point.
- `$PROJECT_DIR/CLAUDE.md` — general usage reference (L60).
- `$PROJECT_DIR/docs/MCP_CLAUDE_CODE_INTEGRATION.md` — troubleshooting guide (L70).