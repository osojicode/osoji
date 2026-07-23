# packages\mcp-debugger\src\cli-entry.ts
@source-hash: 9e233d542df4213f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:04Z

## CLI Entry Point for `mcp-debugger` npx Usage

### Purpose
Publishable CLI shim (`packages/mcp-debugger/src/cli-entry.ts`) that:
1. Silences console output before any imports to prevent stdout pollution in MCP transport modes (stdio/SSE).
2. Strips quote characters from `process.argv`.
3. Delegates to the core `main()` from `src/index.js`.

---

### Console Silencing IIFE (L9–62)
Runs **synchronously before any imports**. Determines whether console should be silenced by checking:
- `hasStdio` (L22): any argv contains `stdio`
- `hasSse` (L23): any argv contains `sse`
- `process.env.CONSOLE_OUTPUT_SILENCED === '1'` (L36)
- No `--transport` arg present AND `process.stdin.isTTY` is falsy (L33–37) — auto-detects piped/MCP mode

Matching logic (`matchesKeyword`, L12–19) strips quotes and uses regex `(?:^|[=:])keyword(?:$|\b)` to match values like `--transport=stdio` or `--transport:stdio`.

If silencing is triggered:
- Sets `process.env.CONSOLE_OUTPUT_SILENCED = '1'` (L41) for downstream imports
- Replaces 13 console methods with no-ops (L44–56)
- Removes and replaces `process` `warning` listener with no-op (L59–60)

---

### argv Cleanup (L65–67)
Strips surrounding single/double quotes from all argv entries using regex `^["'](.*)["']$`. Runs at module level before any processing.

---

### Auto-start Prevention (L70)
Sets `process.env.DEBUG_MCP_SKIP_AUTO_START = '1'` to signal `src/index.js` not to auto-invoke `main()` on import. This allows the shim to control invocation timing.

---

### `batteries-included.js` Import (L73)
Side-effect import ensuring all adapters are bundled in the output package for standalone npx use.

---

### `bootstrap()` (L75–89)
Async function that:
1. Dynamically imports `main` from `../../../src/index.js` (L78)
2. Calls `main()` (L81)
3. On error: conditionally logs (if console not silenced) and calls `process.exit(1)` (L84–88)

Bootstrap is immediately invoked at module level (L91–97) with its own catch handler following the same silencing check pattern.

---

### Key Architectural Decisions
- **IIFE must be first**: Console silencing must precede any `import` statements (TypeScript hoists `import` declarations, so the IIFE pattern in a top-level expression prevents this).
- **Dynamic import for `main`**: Prevents `src/index.js` from auto-running before silencing/env setup is complete.
- **Dual catch handlers**: Both `bootstrap()` internal catch (L82–88) and the outer `.catch` (L91–97) guard against fatal errors at different promise chain levels.
- **Environment variable as cross-module signal**: `CONSOLE_OUTPUT_SILENCED` and `DEBUG_MCP_SKIP_AUTO_START` propagate silencing/startup control to lazily-loaded modules.

---

### Environment Variables
| Variable | Set at | Purpose |
|---|---|---|
| `CONSOLE_OUTPUT_SILENCED` | L36 (read), L41 (set) | Signals console is silenced to all downstream code |
| `DEBUG_MCP_SKIP_AUTO_START` | L70 | Prevents auto-run in `src/index.js` |
