# tests\e2e\mcp-server-smoke-java-evaluate.test.ts
@source-hash: ea84510d268aea7f
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:33Z

## Java Expression Evaluation Smoke Test via MCP Interface

End-to-end test suite that validates the `ExprEvaluator` in `JdiDapServer` through the `evaluate_expression` MCP tool. Requires a real JDK installation (`java`/`javac` on PATH); gracefully skips if absent.

### Test Architecture
- Spawns the MCP server (`dist/index.js`) as a child process via `StdioClientTransport` (L94–101)
- Connects an MCP `Client` (L103–110)
- Uses `prepareJavaExample('ExprTest')` to compile/locate the `ExprTest.java` fixture (L154)
- Sets a breakpoint on **line 37** of `ExprTest.java` (inside `run()`, after all locals are assigned) (L168–173)
- Waits for the breakpoint to be hit via polling `get_stack_trace` (L195, via `waitForPausedState`)
- Evaluates ~40 expressions covering all language feature categories (L206–308)
- Cleans up the debug session in `afterEach`/`afterAll` (L133–141, L114–131)

### Key Helper Functions

- **`waitForPausedState`** (L37–51): Polls `get_stack_trace` MCP tool up to `maxAttempts` (default 20) times at `intervalMs` intervals (default 500ms). Returns stack frame data when non-empty, or `null` on timeout.

- **`evalExpr`** (L56–75): Calls the `evaluate_expression` MCP tool, parses result via `parseSdkToolResult`, throws on `response.success === false`, returns `response.result ?? ''`.

### MCP Tool Calls (in test flow)
1. `create_debug_session` — language: `'java'`, name: `'java-eval-test'` (L159–161)
2. `set_breakpoint` — file: `testJavaFile`, line: `37` (L169–171)
3. `start_debugging` — with `dapLaunchArgs`: `{ mainClass, classpath, cwd, stopOnEntry: false }` (L177–189)
4. `get_stack_trace` — polled until paused (L44)
5. `evaluate_expression` — called ~40 times for each expression category (L61–64)
6. `continue_execution` — to resume after all assertions (L313)
7. `close_debug_session` — in `afterEach` and `afterAll` teardown (L117, L136)

### Expression Categories Tested (L202–308)
| Category | Examples |
|---|---|
| Literals | `42`, `"hello"`, `true`, `null` |
| Local variables | `x` (10), `msg` ("hello") |
| `this` + instance fields | `this.instanceField`, `this.name`, `this.flag` |
| Implicit `this` | `instanceField`, `flag` |
| Method invocation (stdlib) | `msg.length()`, `msg.toUpperCase()` |
| Instance methods | `add(1, 2)`, `greet("World")` |
| Array access | `numbers[0]`, `numbers.length` |
| 2D array access | `matrix[0][0]`, `matrix[1][1]` |
| Arithmetic | `x + 5`, `10 / 3`, `10 % 3` |
| String concatenation | `"Hello, " + name` |
| Comparisons | `x > 5`, `x == 10`, `x != 10` |
| Boolean operators | `flag && true`, `flag \|\| false`, `!flag` |
| Grouping | `(x + 5) * 2` |
| Unary minus | `-x`, `-42` |
| `instanceof` (interface hierarchy, Issue 14) | `this instanceof ExprTest/Greeter/FormalGreeter`, `msg instanceof String` |

### ExprTest.java Fixture Contract (assumed from comments)
- Breakpoint line: **37** (inside `run()` method)
- Local vars at breakpoint: `int x = 10`, `double pi = 3.14`, `String msg = "hello"`, `Integer boxed = 42`
- Instance fields: `instanceField=42`, `name="test"`, `numbers={10,20,30}`, `matrix={{1,2},{3,4}}`, `flag=true`, `greeterRef=this`
- Methods: `add(int,int)`, `greet(String)`
- Class hierarchy: `ExprTest implements FormalGreeter extends Greeter`

### JDK Guard Pattern
JDK availability is checked **twice**: once in `beforeAll` (L84–90) and once at the start of the test (L146–152). Both use `execSync('java -version')` / `execSync('javac -version')`. If absent, `beforeAll` returns early (leaving `mcpClient = null`) and the test returns early (no skip/skip marker — returns without assertions).

### Timeouts
- `beforeAll`: 30 000ms (L112)
- Test case: 120 000ms (L317)

### Dependencies
- `@modelcontextprotocol/sdk` — `Client`, `StdioClientTransport`
- `./smoke-test-utils.js` — `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils.js` — `prepareJavaExample`
- `vitest` — test framework