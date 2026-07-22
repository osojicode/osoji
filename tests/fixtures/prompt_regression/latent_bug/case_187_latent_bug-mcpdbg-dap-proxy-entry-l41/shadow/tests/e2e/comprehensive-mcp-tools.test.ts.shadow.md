# tests\e2e\comprehensive-mcp-tools.test.ts
@source-hash: ff13d3cf9ef2c217
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:30Z

## Comprehensive MCP Debugger E2E Test Suite

End-to-end test that exercises all 20 MCP debugger tools across 8 language adapters (Python, JavaScript, Mock, Rust, Go, .NET, Java, Ruby). Produces a PASS/FAIL/SKIP matrix report and writes JSON results to `tests/e2e/comprehensive-test-results.json`.

---

### Architecture Overview

**Single Vitest `describe` block** (L175) contains:
- Language-agnostic tool tests (tools 1 & 3, L267–299)
- A `for (const lang of LANGUAGES)` loop (L305) generating per-language nested `describe` blocks for all remaining tools
- `beforeAll` (L184–243): connects MCP client via StdioClientTransport, pre-compiles Go/dotnet/Java examples
- `afterAll` (L245–252): prints results matrix, closes client/transport
- `afterEach` (L254–261): closes `currentSessionId` if set

---

### Key Types & Constants

**`ToolStatus`** (L27): `'PASS' | 'FAIL' | 'SKIP' | 'PENDING'`

**`ToolResult`** (L29–35): `{ tool, language, status, detail, duration? }`

**`LangDef`** (L124–132): Per-language config — `language`, `script` (source file), `launchScript` (DAP launch path, defaults to `script`), `bpLine`, `available`, `skipReason`, `dapLaunchArgs`

**`results: ToolResult[]`** (L37): Module-level accumulator, appended by `record()`, consumed by `printSummary()`

**`ALL_TOOLS`** (L150–171): Ordered list of all 20 MCP tool names

**`LANGUAGES`** (L134–146): 8 `LangDef` entries. Go and dotnet have `launchScript` set to `undefined` initially; set to compiled binary in `beforeAll`. Java uses `dapLaunchArgs.mainClass/classpath/cwd`.

---

### Functions

**`record(tool, language, status, detail, duration?)`** (L39–43): Pushes to `results[]` and console-logs with icon (`✓/✗/⊘/…`).

**`hasCommand(cmd)`** (L68–75): Executes shell command with 5s timeout; returns bool. Used to detect Rust, Go/Delve, Ruby/rdbg, dotnet/netcoredbg, Java toolchains.

**`ensureGoBuild()`** (L89–97): Compiles `examples/go/hello_world.go` with `-gcflags="all=-N -l"` (debug info), returns binary path.

**`ensureDotnetBuild()`** (L99–112): Checks for pre-built `dotnet.dll` across TFMs (`net10.0` → `net6.0`), builds if missing, throws if still not found.

**`ensureJavaBuild()`** (L114–116): Delegates to `prepareJavaExample('HelloWorld')`.

**`printSummary()`** (L772–814, internal): Builds tool×language matrix from `results[]`, prints to console, writes JSON to `tests/e2e/comprehensive-test-results.json`. Groups results using `Map<tool, Map<language, ToolResult>>`.

---

### Test Structure (per-language loop, L305–768)

Each available language runs these `it()` blocks:
- **Tool 2** (L319): `create_debug_session` — captures `currentSessionId`
- **Tool 3** (L338): `list_debug_sessions` with active session
- **Tool 4** (L360): `set_breakpoint` on `lang.script` at `lang.bpLine`
- **Tool 5** (L385): `get_source_context` — checks for any source content field
- **Tools 6–15,19** (L416, real languages only): Full debug workflow — `start_debugging` → 4s wait → `get_stack_trace` → `get_scopes` → `get_variables` → `get_local_variables` → `evaluate_expression` (`1+2`) → `step_over` → `step_into` → `step_out` → `continue_execution` → `close_debug_session`; non-critical steps use try/catch without rethrow
- **Mock adapter** (L608–677): Reduced lifecycle — `create_debug_session` → `set_breakpoint` → `start_debugging` → 2s wait → inspection tools loop → `close_debug_session`; skips scopes/evaluate/step_into/step_out
- **Tool 16** (L682): `pause_execution` — always PASS (not implemented, error expected)
- **Tool 18** (L706): `attach_to_process` on port 5678/localhost — expects ECONNREFUSED/timeout
- **Tool 19** (L743): `detach_from_process` — expects graceful error when no process attached

---

### Toolchain Detection (module-level, L77–85)

| Variable | Command(s) |
|---|---|
| `hasRust` | `rustc --version` |
| `hasGo` | `go version` + `dlv version` |
| `hasRuby` | `ruby --version` + `rdbg --version` |
| `hasDotnet` | `dotnet --version` + (`NETCOREDBG_PATH` env OR `netcoredbg --version`) |
| `hasJava` | `java -version` + `javac -version` |

---

### Breakpoint Lines (L58–64)

| Language | Line | Note |
|---|---|---|
| Python | 10 | After `a=1, b=2` assignments |
| JS | 9 | `let a = 1` |
| Rust | 19 | After `name, version, is_awesome, result` in scope |
| Go | 13 | `fmt.Println(message)` — `message` in scope |
| .NET | 15 | `int y = 20` — `x=10` in scope |
| Java | 24 | `int sum = add(x, y)` |
| Ruby | 15 | First loop iteration — `i, results` in scope |

---

### External Dependencies

- `@modelcontextprotocol/sdk/client/index.js`: `Client` — MCP client
- `@modelcontextprotocol/sdk/client/stdio.js`: `StdioClientTransport` — spawns MCP server via `process.execPath dist/index.js`
- `./smoke-test-utils.js`: `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils.js`: `prepareJavaExample`

---

### Output Artifact

`tests/e2e/comprehensive-test-results.json` (L811): `{ results: ToolResult[], summary: { total, pass, fail, skip }, timestamp }` — written by `printSummary()` in `afterAll`.
