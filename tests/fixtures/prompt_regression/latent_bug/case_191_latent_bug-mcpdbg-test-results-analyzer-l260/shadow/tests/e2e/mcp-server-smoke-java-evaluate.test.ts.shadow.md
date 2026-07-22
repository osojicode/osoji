# tests\e2e\mcp-server-smoke-java-evaluate.test.ts
@source-hash: ea84510d268aea7f
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:19Z

## Java Expression Evaluation Smoke Tests via MCP Interface

End-to-end test suite verifying the `evaluate_expression` MCP tool against a real JVM debug session. Exercises the `ExprEvaluator` in `JdiDapServer` by pausing at a breakpoint in `ExprTest.java` and evaluating a comprehensive set of Java expressions.

### Setup & Teardown (L82–142)

- **`beforeAll` (L82–112)**: Guards against missing JDK via `execSync('java -version')` / `execSync('javac -version')`. If JDK absent, skips setup — individual tests perform the same check and return early. Spawns the MCP server via `StdioClientTransport` pointing at `dist/index.js`, connects an MCP `Client`.
- **`afterAll` (L114–131)**: Closes the debug session (if open), then closes MCP client and transport.
- **`afterEach` (L133–142)**: Closes the debug session after each test and resets `sessionId` to `null`, ensuring test isolation.

### Helper Functions

- **`waitForPausedState` (L37–51)**: Polls `get_stack_trace` tool up to `maxAttempts` times (default 20) with `intervalMs` ms delay (default 500ms). Returns the stack-frame response when non-empty frames are found, or `null` on timeout.
- **`evalExpr` (L56–75)**: Calls the `evaluate_expression` MCP tool, parses the result via `parseSdkToolResult`, throws on `response.success === false`, and returns `response.result ?? ''`.

### Main Test: `should evaluate expressions at a breakpoint in ExprTest` (L144–317, timeout 120s)

**Flow:**
1. JDK guard check (L146–152) — early return if absent.
2. `prepareJavaExample('ExprTest')` (L154) — compiles `ExprTest.java` with `-g`, returns `{ sourcePath, classDir, mainClass }`.
3. `create_debug_session` (L158–164) — language `'java'`, captures `sessionId`.
4. `set_breakpoint` at `ExprTest.java` line 37 (L168–173) — inside `run()` after all locals assigned.
5. `start_debugging` (L176–191) — with `dapLaunchArgs: { mainClass, classpath: testClassDir, cwd: testClassDir, stopOnEntry: false }`.
6. `waitForPausedState` (L195) — polls up to 30 attempts × 500ms (15s total).
7. Validates top frame name contains `'run'` (L200).
8. **Expression categories tested:**
   - Literals: `42`, `"hello"`, `true`, `null` (L206–209)
   - Local variables: `x` → `'10'`, `msg` → `'"hello"'` (L214–215)
   - `this` and explicit field access: `instanceField=42`, `name="test"`, `flag=true` (L222–224)
   - Implicit `this` field access: `instanceField`, `flag` (L229–230)
   - Method invocation on local: `msg.length()` → `'5'`, `msg.toUpperCase()` → `'"HELLO"'` (L235–236)
   - Instance methods: `add(1, 2)` → `'3'`, `greet("World")` → `'"Hello, World"'` (L241–242)
   - Array access: `numbers[0]`, `numbers[2]`, `numbers.length` (L247–249)
   - 2D array: `matrix[0][0]` → `'1'`, `matrix[1][1]` → `'4'` (L254–255)
   - Arithmetic: `+`, `*`, `/`, `%` (L260–263)
   - String concatenation: `"Hello, " + name` → `'"Hello, test"'` (L268–269)
   - Comparisons: `>`, `<`, `==`, `!=`, `>=`, `<=` (L274–279)
   - Boolean operators: `&&`, `||`, `!` (L284–287)
   - Grouping: `(x + 5) * 2` → `'30'` (L292–293)
   - Unary minus: `-x` → `'-10'`, `-42` → `'-42'` (L298–299)
   - `instanceof` with interface hierarchy (`ExprTest`, `Greeter`, `FormalGreeter`, `String`) (L304–308)
9. `continue_execution` to finish (L313–314).

### Key Paths & Constants
- MCP server binary: `path.join(ROOT, 'dist', 'index.js')` (L96)
- `ROOT` resolved as `../../` from `__dirname` (L32)
- Breakpoint line: **37** in `ExprTest.java` (L171)
- Poll config: 30 attempts × 500ms for paused state (L195)
- `beforeAll` timeout: 30s (L112); test timeout: 120s (L317)

### Dependencies
- `@modelcontextprotocol/sdk` — `Client`, `StdioClientTransport`
- `./smoke-test-utils` — `parseSdkToolResult`, `callToolSafely`
- `./java-example-utils` — `prepareJavaExample` (compiles ExprTest.java)
- `child_process.execSync` — JDK availability check
