# src\session\session-manager-data.ts
@source-hash: df0db5c943d46e36
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:17Z

## SessionManagerData (L19–251)

Abstract class extending `SessionManagerCore` that provides DAP (Debug Adapter Protocol) data retrieval operations. Acts as a mixin layer in a class hierarchy for session management, adding variable inspection, stack trace, scope, and convenience local-variable fetching capabilities.

### Class Hierarchy
`SessionManagerData extends SessionManagerCore` — consumers are expected to extend this class further (it is `abstract`).

### Key Methods

#### `selectPolicy(language)` (L23–25) — protected
Delegates to `getPolicyForLanguage(language)` from `@debugmcp/shared`. Returns an `AdapterPolicy` for the given debug language. Used by `getStackTrace` (L102) and `getLocalVariables` (L209) to apply language-specific filtering/extraction logic.

#### `getVariables(sessionId, variablesReference)` (L27–60) — public, async
- Guards: requires active proxy (`proxyManager.isRunning()`) and session state `PAUSED`.
- Sends DAP `variables` request with `variablesReference`.
- Maps `DebugProtocol.Variable` → internal `Variable` shape: `{ name, value, type (defaults to "<unknown_type>"), variablesReference, expandable: variablesReference > 0 }`.
- Returns `[]` on guard failure, empty response, or error (never throws).

#### `getStackTrace(sessionId, threadId?, includeInternals?)` (L62–118) — public, async
- Guards: same proxy+state checks as `getVariables`.
- Resolves effective thread: prefers explicit `threadId`, falls back to `session.proxyManager.getCurrentThreadId()`.
- Sends DAP `stackTrace` request; **throws** on `response.success === false` (issue #124 guard, L90–92).
- Maps `DebugProtocol.StackFrame` → `StackFrame`: `{ id, name, file: source.path || source.name || "<unknown_source>", line, column }`.
- Applies `policy.filterStackFrames(frames, includeInternals)` if defined on the policy (L103–107).
- **Throws** on error or missing stack frames (unlike `getVariables` which returns `[]`).

#### `getScopes(sessionId, frameId)` (L120–148) — public, async
- Guards: same proxy+state checks.
- Sends DAP `scopes` request; returns raw `DebugProtocol.Scope[]` (no transformation).
- Returns `[]` on guard failure, empty response, or error (never throws).

#### `getLocalVariables(sessionId, includeSpecial?)` (L156–251) — public, async
Orchestrates a 5-step pipeline:
1. `getStackTrace(sessionId)` — gets all frames.
2. For each frame: `getScopes(sessionId, frame.id)` — builds `scopesMap: Record<frameId, Scope[]>`.
3. For each scope with `variablesReference > 0`: `getVariables(sessionId, scope.variablesReference)` — builds `variablesMap: Record<variablesReference, Variable[]>`.
4. `selectPolicy(session.language)` — get adapter policy.
5. If `policy.extractLocalVariables` defined: call it with all maps + `includeSpecial`. Fallback (L225–230): first non-global scope from top frame.
- Returns `{ variables, frame: { name, file, line } | null, scopeName: string | null }`.
- **Throws** on error (issue #124 propagation, L249).

### Guard Pattern
All methods check:
1. `session.proxyManager` exists and `isRunning()` — returns empty/null result if not.
2. `session.state === SessionState.PAUSED` — returns empty/null result if not.
`getStackTrace` and `getLocalVariables` throw rather than silently returning empty on actual errors.

### Dependencies
- `@debugmcp/shared`: `Variable`, `StackFrame`, `SessionState`, `AdapterPolicy`, `getPolicyForLanguage`, `DebugLanguage`
- `./session-manager-core.js`: `SessionManagerCore` (provides `_getSessionById`, `logger`, and session object shape)
- `@vscode/debugprotocol`: `DebugProtocol` (typed DAP requests/responses)

### Notable Patterns
- **Error propagation asymmetry**: `getVariables`/`getScopes` swallow errors and return `[]`; `getStackTrace`/`getLocalVariables` propagate errors (referenced as issue #124 fix).
- **Policy-driven extensibility**: Language-specific `AdapterPolicy` hooks (`filterStackFrames`, `extractLocalVariables`, `getLocalScopeName`) allow per-language customization without modifying this class.
- **Inline DAP type mapping**: DAP protocol types are mapped to internal shared types inline within each method.