# src\session\session-manager-data.ts
@source-hash: df0db5c943d46e36
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:41Z

## `SessionManagerData` (L19–251)

Abstract class extending `SessionManagerCore` that provides DAP (Debug Adapter Protocol) data-retrieval operations for paused debug sessions. All methods require the session to be in `SessionState.PAUSED` with an active proxy. Sits in the middle of the session manager inheritance chain.

### Class Hierarchy
```
SessionManagerCore → SessionManagerData → (concrete SessionManager)
```

### Key Methods

#### `selectPolicy(language)` (L23–25)
Protected helper. Maps a language string/enum to an `AdapterPolicy` via `getPolicyForLanguage`. Used internally by `getStackTrace` and `getLocalVariables` to apply language-specific filtering and extraction.

#### `getVariables(sessionId, variablesReference)` (L27–60)
Sends DAP `variables` request for a given `variablesReference` handle. Maps `DebugProtocol.Variable` to internal `Variable` shape: `{ name, value, type, variablesReference, expandable }`. `expandable` is `variablesReference > 0`. Returns `[]` on any error or when not paused.

#### `getStackTrace(sessionId, threadId?, includeInternals?)` (L62–118)
Sends DAP `stackTrace` request. Uses `session.proxyManager.getCurrentThreadId()` if `threadId` not provided. Applies `policy.filterStackFrames` when available. **Throws** on DAP failure (`response.success === false`) or missing stack frames — unlike `getVariables`/`getScopes` which return `[]`. Maps to `StackFrame`: `{ id, name, file, line, column }`.

#### `getScopes(sessionId, frameId)` (L120–148)
Sends DAP `scopes` request for a stack frame ID. Returns raw `DebugProtocol.Scope[]`. Returns `[]` on error or when not paused.

#### `getLocalVariables(sessionId, includeSpecial?)` (L156–251)
High-level convenience orchestrator. Pipeline:
1. `getStackTrace` → all frames
2. `getScopes` for each frame → `scopesMap: Record<frameId, Scope[]>`
3. `getVariables` for each scope's `variablesReference` → `variablesMap: Record<variablesReference, Variable[]>`
4. `selectPolicy` → `AdapterPolicy`
5. `policy.extractLocalVariables(stackFrames, scopesMap, variablesMap, includeSpecial)` or fallback to first non-global scope of top frame
6. `policy.getLocalScopeName()` for scope label

Returns `{ variables, frame: { name, file, line } | null, scopeName: string | null }`. **Throws** on failure (per issue #124 fix).

### Guard Pattern (repeated across all methods, L31–38, L67–80, L124–131, L165–172)
1. Check `session.proxyManager` exists and `isRunning()` → return empty/null
2. Check `session.state === SessionState.PAUSED` → return empty/null

`getStackTrace` and `getLocalVariables` **throw** instead of returning empty on downstream failure; `getVariables` and `getScopes` swallow errors and return `[]`.

### Notable Design Decisions
- **Issue #124 fix** (L87–92, L246–249): DAP failures are propagated as thrown errors rather than silently returning empty results.
- `getLocalVariables` iterates ALL stack frames for scopes (L187–192), supporting closure variable capture across frames.
- Fallback at L224–230: if policy lacks `extractLocalVariables`, uses first non-`global`-named scope of the top frame.
- `type` defaults to `"<unknown_type>"` and `file` defaults to `"<unknown_source>"` when DAP provides `undefined`.

### Dependencies
- `SessionManagerCore`: provides `_getSessionById(sessionId)` and `this.logger`
- `@debugmcp/shared`: `Variable`, `StackFrame`, `SessionState`, `AdapterPolicy`, `getPolicyForLanguage`, `DebugLanguage`
- `@vscode/debugprotocol`: `DebugProtocol` namespace for typed DAP request/response shapes