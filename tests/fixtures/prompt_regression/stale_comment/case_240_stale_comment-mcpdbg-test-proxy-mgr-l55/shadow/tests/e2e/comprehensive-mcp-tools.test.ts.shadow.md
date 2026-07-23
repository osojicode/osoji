# tests\e2e\comprehensive-mcp-tools.test.ts
@source-hash: ad6f51d08ff5743c
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:34:10Z

## Comprehensive MCP Debugger End-to-End Test Suite

### Purpose
Tests all 20 MCP debugger tools across all supported language adapters (Python, JavaScript, Mock, Rust, Ruby, Go, .NET, Java). Produces a PASS/FAIL/SKIP matrix report and writes JSON results to `tests/e2e/comprehensive-test-results.json`.

---

### Architecture & Flow

**Single Vitest `describe` block** (L175–815) wraps all tests with shared MCP client lifecycle:
- `beforeAll` (L184–243): Starts MCP server via `StdioClientTransport` pointing to `dist/index.js`, connects client, pre-compiles Go/Dotnet/Java artifacts. Timeout: 60s.
- `afterAll` (L245–252): Calls `printSummary()`, closes client and transport.
- `afterEach` (L254–261): Closes `currentSessionId` session via `close_debug_session` if set, resets to `null`.

**Language availability** is detected at module load time (L77–85) using `execSync` with 5s timeout via `hasCommand()` (L68–75). Go requires both `go` and `dlv`; Ruby requires both `ruby` and `rdbg`; .NET checks for `netcoredbg` or `NETCOREDBG_PATH` env var; Java requires both `java` and `javac`.

---

### Key Constants & Data Structures

**`ToolStatus`** (L27): `'PASS' | 'FAIL' | 'SKIP' | 'PENDING'`

**`ToolResult`** interface (L29–35): `{ tool, language, status, detail, duration? }`

**`results: ToolResult[]`** (L37): Module-level accumulator for all test outcomes.

**`ALL_TOOLS`** (L150–171): Array of 20 tool name strings in canonical order.

**`LANGUAGES: LangDef[]`** (L134–146): Array of 8 language definitions. Each has:
- `language`, `script` (source file path), `launchScript?` (runtime binary/dll — set in beforeAll for Go/Dotnet), `bpLine`, `available`, `skipReason?`, `dapLaunchArgs?`

**Breakpoint lines** (L58–64): Language-specific executable lines chosen to have local variables in scope.

---

### Example File Paths (L47–54)

| Constant | Path |
|---|---|
| `PYTHON_SCRIPT` | `examples/python/simple_test.py` |
| `JS_SCRIPT` | `examples/javascript/simple_test.js` |
| `RUST_SCRIPT` | `examples/rust/hello_world/src/main.rs` |
| `GO_SCRIPT` | `examples/go/hello_world.go` |
| `DOTNET_SCRIPT` | `examples/dotnet/Program.cs` |
| `JAVA_SCRIPT` | `examples/java/HelloWorld.java` |
| `RUBY_SCRIPT` | `examples/ruby/fizzbuzz.rb` |

---

### Key Functions

**`record(tool, language, status, detail, duration?)`** (L39–43): Pushes to `results[]`, logs with status icon (`✓/✗/⊘/…`).

**`hasCommand(cmd)`** (L68–75): Returns `true` if `execSync` succeeds with 5s timeout.

**`ensureGoBuild()`** (L89–97): Compiles Go binary with `-gcflags="all=-N -l"` (debug info), returns binary path. Output: `examples/go/hello_world_test[.exe]`.

**`ensureDotnetBuild()`** (L99–112): Checks pre-built DLLs for `net10.0`–`net6.0` TFMs, runs `dotnet build -c Debug` if not found, returns first found `.dll` path.

**`ensureJavaBuild()`** (L114–116): Delegates to `prepareJavaExample('HelloWorld')` from `java-example-utils.js`.

**`printSummary()`** (L772–813): Prints tool×language matrix to console, writes JSON to `tests/e2e/comprehensive-test-results.json`.

---

### Test Structure Per Language (L305–768)

For each language in `LANGUAGES`:
- **Unavailable languages** (L307–315): Records `SKIP` for all non-global tools, calls `it.skip()`.
- **Tool 2** (L319–334): `create_debug_session` — asserts `sessionId` defined.
- **Tool 3** (L338–356): `list_debug_sessions` with active session.
- **Tool 4** (L360–381): `set_breakpoint` on `lang.script:lang.bpLine`.
- **Tool 5** (L385–410): `get_source_context` — checks any of `lineContent/surrounding/source/lines/content` fields.
- **Tools 6–15, 20** (L416–605): Full debug workflow (real languages only):
  - `start_debugging` → 4s wait → `get_stack_trace` → `get_scopes` → `get_variables` → `get_local_variables` → `evaluate_expression` (`1 + 2`, expects `3`) → `step_over` → `step_into` → `step_out` → `continue_execution` → `close_debug_session`
- **Mock adapter** (L608–677): Abbreviated lifecycle: `create` → `set_breakpoint` → `start_debugging` → 2s wait → `get_stack_trace/get_local_variables/step_over/continue_execution` → `close`. Skips: `get_source_context`, `get_scopes`, `get_variables`, `evaluate_expression`, `step_into`, `step_out`.
- **Tool 16** (L682–702): `pause_execution` — both success and error treated as PASS (documented as "Not Implemented").
- **Tool 18** (L706–739): `attach_to_process` on port 5678/localhost — connection refused / timeout errors treated as PASS.
- **Tool 19** (L743–766): `detach_from_process` — errors treated as PASS (no process attached).

---

### Language-Agnostic Tests (Top-Level)
- **Tool 1** (L267–284): `list_supported_languages` — verifies ≥2 languages returned.
- **Tool 3** (L290–299): `list_debug_sessions` when no sessions exist.

---

### Dependencies
- `@modelcontextprotocol/sdk` — `Client`, `StdioClientTransport`
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils.js` — `prepareJavaExample`
- MCP server binary: `dist/index.js` run via Node.js

---

### Output
- Console matrix with PASS/FAIL/SKIP/PENDING per tool per language
- `tests/e2e/comprehensive-test-results.json`: `{ results, summary: { total, pass, fail, skip }, timestamp }`
