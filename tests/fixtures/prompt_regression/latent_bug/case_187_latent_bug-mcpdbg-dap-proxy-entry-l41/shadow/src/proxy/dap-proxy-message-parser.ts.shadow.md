# src\proxy\dap-proxy-message-parser.ts
@source-hash: 4ecf030741f4e5db
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:24Z

## MessageParser (L12-187)

Static utility class that parses, validates, and type-narrows messages received from the parent process over IPC for the DAP Proxy. Acts as the sole runtime validation boundary between raw IPC data and typed `ParentCommand` variants.

### Primary Responsibility
Convert `unknown` IPC messages (strings or objects) into one of three typed `ParentCommand` union members (`ProxyInitPayload`, `DapCommandPayload`, `TerminatePayload`), throwing descriptive `Error` on invalid input.

---

### Key Methods

#### `parseCommand(message: unknown): ParentCommand` (L17-52)
Entry point. Handles two input shapes:
- **String**: JSON-parses then recursively calls itself with the parsed object (L19-26).
- **Object**: Validates presence of `cmd` field (L36-38), then dispatches to a per-command validator via `switch` on `obj.cmd` values `'init'`, `'dap'`, `'terminate'` (L42-51). Throws on unknown `cmd`.

#### `validateInitPayload(payload: unknown): ProxyInitPayload` (L58-137)
Validates `init` command. Logic:
- Required string fields: `sessionId`, `executablePath`, `adapterHost`, `logDir`, `scriptPath` (L62-70).
- `adapterPort`: coerces string→number to handle double-stringify bug (L73-76), then validates as positive integer ≤65535 (L79-81).
- Optional string `language` (L84-86), optional array `scriptArgs` (L88-90).
- Boolean coercion for `stopOnEntry`, `justMyCode`, `dryRunSpawn` from `'true'`/`'false'` strings (L93-96), then type-checks them (L98-108).
- `initialBreakpoints`: validates as array of objects each with string `file`, number `line` (with string coercion, L122-125), and optional string `condition` (L116-133).
- Returns via double `as unknown as ProxyInitPayload` cast (L136).

#### `validateDapPayload(payload: unknown): DapCommandPayload` (L143-169)
Validates `dap` command:
- Required string fields: `sessionId`, `requestId`, `dapCommand` (L147-153).
- `dapArgs`: rejects `null` explicitly, allows `undefined` or any non-null value (L156-158).
- `timeoutMs`: deletes the field if present but not a finite positive number (L162-165) — falls back to defaults downstream.
- Returns via double cast (L168).

#### `validateTerminatePayload(payload: unknown): TerminatePayload` (L175-185)
Validates `terminate` command:
- `sessionId` is optional (emergency shutdown scenario), but if present must be a string (L179-181).
- Returns via double cast (L184).

---

### Notable Patterns
- **Double-stringify bug workaround** (L73-76, L93-96, L122-125): Coerces string-encoded numbers and booleans that arise from Claude Code SSE serialization. This is a known upstream quirk explicitly commented.
- **Mutation of input `obj`**: Both `validateInitPayload` and `validateDapPayload` mutate the cast `Record<string, unknown>` in place (e.g., coercing field values) before the final cast. This is intentional to normalize the payload before returning it as the typed interface.
- **Recursive `parseCommand`**: String input triggers JSON.parse + recursive call (L22), cleanly separating the string-wrapping concern.
- All methods are `static`; the class is a namespace-style utility with no instance state.

---

### Dependencies
- `ParentCommand`, `ProxyInitPayload`, `DapCommandPayload`, `TerminatePayload` from `./dap-proxy-interfaces.js` — these are the target types after validation. Their field definitions drive the validation logic here.