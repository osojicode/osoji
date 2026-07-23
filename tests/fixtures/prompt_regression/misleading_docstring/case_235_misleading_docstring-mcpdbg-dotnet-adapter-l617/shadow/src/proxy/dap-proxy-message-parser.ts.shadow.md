# src\proxy\dap-proxy-message-parser.ts
@source-hash: 4ecf030741f4e5db
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:15Z

## MessageParser (L12-187)

Static utility class for parsing and validating inbound IPC messages from the parent process in the DAP Proxy subsystem. All methods are static — class is never instantiated.

### Primary Responsibility
Deserializes raw IPC messages (string or object) into typed `ParentCommand` variants (`ProxyInitPayload`, `DapCommandPayload`, `TerminatePayload`). Handles a known double-stringify bug from Claude Code SSE transport by coercing string-encoded numbers and booleans to their proper types before validation.

---

### Key Methods

#### `parseCommand(message: unknown): ParentCommand` (L17-52)
Entry point for all inbound messages. Two-phase dispatch:
1. If `message` is a `string`, JSON-parses it and recursively calls itself (L21-22).
2. Asserts `message` is an object, checks for a required `cmd` string field, then routes to a specific validator via `switch` on `cmd` values: `'init'` → `validateInitPayload`, `'dap'` → `validateDapPayload`, `'terminate'` → `validateTerminatePayload` (L42-51). Throws `Error` on any unknown `cmd` or structural mismatch.

#### `validateInitPayload(payload: unknown): ProxyInitPayload` (L58-137)
Validates the `init` command. Required string fields (L62-64): `sessionId`, `executablePath`, `adapterHost`, `logDir`, `scriptPath`. Required numeric field `adapterPort` (L79); coerces from string first (L73-76). Optional fields with type guards: `language` (string), `scriptArgs` (array), `stopOnEntry`/`justMyCode`/`dryRunSpawn` (booleans — coerced from `'true'`/`'false'` strings at L93-96). Validates `initialBreakpoints` array elements: each must have `file` (string) and `line` (number; coerced from string at L122-124), optional `condition` (string).

#### `validateDapPayload(payload: unknown): DapCommandPayload` (L143-169)
Validates the `dap` command. Required string fields (L147): `sessionId`, `requestId`, `dapCommand`. Optional `dapArgs` must not be `null` if present (L156-158). Optional `timeoutMs` must be a finite positive number; silently deleted if invalid (L162-165).

#### `validateTerminatePayload(payload: unknown): TerminatePayload` (L175-185)
Validates the `terminate` command. `sessionId` is optional but must be a string if present (L179-181). No other required fields — supports emergency shutdown without a session context.

---

### Design Patterns & Constraints

- **Mutation-based coercion**: The `obj` cast to `Record<string, unknown>` is mutated in-place before type assertion (e.g., `obj.adapterPort = parsed`). The final `return obj as unknown as XPayload` relies on this mutation being reflected in the returned value.
- **String→primitive coercion**: Handles a documented bug ("Claude Code SSE double-stringify bug") where numeric and boolean values arrive as strings. Applied to: `adapterPort`, `initialBreakpoints[].line`, `stopOnEntry`, `justMyCode`, `dryRunSpawn`.
- **Recursive parsing**: `parseCommand` recurses once for string inputs; no risk of infinite recursion since the parsed result will be an object.
- **No schema library**: All validation is manual and imperative. Throws `Error` (not typed errors) on failure.
- **`terminate` leniency**: Only command that succeeds with no `sessionId`, by design for emergency shutdown scenarios (L178 comment).