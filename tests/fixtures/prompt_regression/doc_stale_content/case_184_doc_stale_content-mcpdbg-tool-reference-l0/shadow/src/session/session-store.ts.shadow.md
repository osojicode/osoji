# src\session\session-store.ts
@source-hash: 805831efbe7dd507
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:31Z

## SessionStore (L68–214)

Pure in-memory data store for debug session lifecycle management. Extracted from `SessionManager` to isolate state management with no external I/O dependencies, enabling straightforward unit testing. Holds all session state in a private `Map<string, ManagedSession>`.

---

### Key Types

**`CreateSessionParams` (L24–28)**
Input for creating a session: `language: DebugLanguage` (required), `name?: string`, `executablePath?: string`.

**`ToolchainValidationState` (L32–39)**
Tracks toolchain compatibility check result: `compatible`, `toolchain`, optional `message`, `suggestions`, `behavior`, `binaryInfo`.

**`ManagedSession` (L44–62)** — extends `DebugSessionInfo`
Internal full-detail session record. Key additional fields:
- `executablePath?: string` — resolved adapter binary path
- `proxyManager?: IProxyManager` — runtime proxy, undefined until session starts
- `breakpoints: Map<string, Breakpoint>` — per-session breakpoint registry
- `sessionLifecycle: SessionLifecycleState` — coarser lifecycle state (CREATED, RUNNING, etc.)
- `executionState?: ExecutionState` — finer execution state (paused, stepping, etc.)
- `logDir?: string`
- `toolchainValidation?: ToolchainValidationState`
- `firstStopHandled?: boolean` — tracks whether the initial adapter stop event has been processed; used by auto-continue logic to handle non-`entry` stop reasons from some adapters (e.g., js-debug)
- `attachMode?: boolean` — suppresses host-side file existence checks for remote/container attach targets

---

### `SessionStore` Class (L68–214)

**Storage:** `private sessions: Map<string, ManagedSession>` (L69)

#### Methods

| Method | Lines | Description |
|---|---|---|
| `selectPolicy(language)` | L74–76 | Delegates to `getPolicyForLanguage`; returns `AdapterPolicy` for the given language |
| `createSession(params)` | L81–120 | Validates language against `DebugLanguage` enum, resolves executable path via policy, generates UUID, constructs `ManagedSession` initialized to `SessionState.CREATED` / `SessionLifecycleState.CREATED`, stores it, returns public `DebugSessionInfo` (strips internal fields) |
| `get(sessionId)` | L125–127 | Returns `ManagedSession \| undefined` |
| `getOrThrow(sessionId)` | L132–138 | Returns `ManagedSession` or throws `SessionNotFoundError` |
| `set(sessionId, session)` | L143–145 | Direct insertion; documented for testing purposes |
| `update(sessionId, updates)` | L150–154 | Shallow-merges partial updates via `Object.assign`, refreshes `updatedAt` |
| `updateState(sessionId, newState)` | L159–165 | Updates `session.state` only if it differs; refreshes `updatedAt` |
| `remove(sessionId)` | L170–172 | Deletes session; returns boolean |
| `getAll()` | L177–186 | Returns array of `DebugSessionInfo` (public shape, strips internals) |
| `getAllManaged()` | L191–193 | Returns all `ManagedSession` objects with full internal data |
| `has(sessionId)` | L198–200 | Existence check |
| `size()` | L205–207 | Count of active sessions |
| `clear()` | L212–214 | Removes all sessions |

---

### Architectural Notes

- **No I/O, no async** — entirely synchronous, no network or file system calls.
- `createSession` returns only `DebugSessionInfo` (public shape) while storing the richer `ManagedSession` internally — callers needing internal state must use `get`/`getOrThrow`.
- `update` uses `Object.assign` (shallow merge), so nested objects (e.g., `breakpoints` Map) are replaced entirely, not merged.
- `selectPolicy` is `public`, allowing callers to inspect the resolved policy without creating a session.
- `set` is explicitly for test injection (L142 comment).

---

### Dependencies

- `uuid.v4` — session ID generation (L8)
- `@debugmcp/shared` — `DebugLanguage`, `SessionState`, `SessionLifecycleState`, `ExecutionState`, `DebugSessionInfo`, `Breakpoint`, `AdapterPolicy`, `getPolicyForLanguage` (L9–18)
- `../errors/debug-errors.js` — `SessionNotFoundError` (L19)
- `../proxy/proxy-manager.js` — `IProxyManager` type (L30)