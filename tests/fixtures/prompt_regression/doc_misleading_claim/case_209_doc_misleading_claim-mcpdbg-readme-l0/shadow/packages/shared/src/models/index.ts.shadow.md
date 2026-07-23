# packages\shared\src\models\index.ts
@source-hash: 41379f34b6ef590d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:21Z

## Session-Related Data Models

Core shared data models for debug session management, used across the monorepo. Defines enums, interfaces, and utility functions for representing debug sessions, their lifecycle/execution states, breakpoints, variables, and stack frames.

---

### Imports
- `DebugProtocol` from `@vscode/debugprotocol` — base DAP types extended by `CustomLaunchRequestArguments`

---

### Interfaces

**`CustomLaunchRequestArguments` (L9–15)**
Extends `DebugProtocol.LaunchRequestArguments` with project-specific launch options: `stopOnEntry`, `justMyCode`, `console`, `cwd`, `env`.

**`GenericAttachConfig` (L32–71)**
Common attach configuration shared across languages. Supports PID, name, and remote attach modes via `identifierType: ProcessIdentifierType`. Includes `[key: string]: unknown` index signature for language-specific extensions.

**`SessionConfig` (L197–204)**
Minimal config to create a session: `language: DebugLanguage`, `name: string`, optional `executablePath`.

**`Breakpoint` (L209–224)**
Breakpoint definition with `id`, `file`, `line`, optional `condition`, optional `suspendPolicy` (`'all' | 'thread'`), `verified` boolean, and optional `message` from DAP adapter.

**`DebugSession` (L229–252)**
Full session model. Carries both legacy `state: SessionState` and new dual-state model (`sessionLifecycle: SessionLifecycleState`, `executionState?: ExecutionState`). `breakpoints` is a `Map<string, Breakpoint>` keyed by ID.

**`DebugSessionInfo` (L257–264)**
Lightweight session summary for list views. Omits breakpoints and dual-state fields. `updatedAt` is optional here.

**`Variable` (L270–281)**
Recursive variable tree: `name`, `value`, `type`, `expandable`, optional `children: Variable[]`.

**`StackFrame` (L286–297)**
Stack frame: `id: number`, `name`, `file`, `line`, optional `column`.

**`DebugLocation` (L302–313)**
Source location with optional context lines array (`sourceLines`) and `sourceLine` index into that array.

**`LanguageSpecificAttachConfig` (L76)**
Type alias: `Record<string, unknown>` — resolved by language adapters.

---

### Enums

**`ProcessIdentifierType` (L20–27)**
`PID = 'pid'`, `NAME = 'name'`, `REMOTE = 'remote'` — discriminant for attach mode.

**`DebugLanguage` (L81–90)**
Supported languages: `PYTHON`, `RUBY`, `JAVASCRIPT`, `RUST`, `GO`, `JAVA`, `DOTNET`, `MOCK` (mock adapter for testing).

**`SessionLifecycleState` (L95–102)**
New model — session existence: `CREATED`, `ACTIVE`, `TERMINATED`.

**`ExecutionState` (L108–119)**
New model — debugger execution state (meaningful only when `SessionLifecycleState.ACTIVE`): `INITIALIZING`, `RUNNING`, `PAUSED`, `TERMINATED`, `ERROR`.

**`SessionState` (L125–140)**
**@deprecated** — legacy combined state. Use `SessionLifecycleState` + `ExecutionState` instead. Values: `CREATED`, `INITIALIZING`, `READY`, `RUNNING`, `PAUSED`, `STOPPED`, `ERROR`.

---

### Functions

**`mapLegacyState(legacyState: SessionState)` (L145–165)**
Converts deprecated `SessionState` → `{ lifecycle: SessionLifecycleState; execution?: ExecutionState }`. Exhaustive switch with `never` guard. Key mappings:
- `CREATED` → `{ lifecycle: CREATED }`
- `INITIALIZING` / `READY` → `{ lifecycle: ACTIVE, execution: INITIALIZING }`
- `RUNNING` → `{ lifecycle: ACTIVE, execution: RUNNING }`
- `PAUSED` → `{ lifecycle: ACTIVE, execution: PAUSED }`
- `STOPPED` → `{ lifecycle: TERMINATED }`
- `ERROR` → `{ lifecycle: ACTIVE, execution: ERROR }`

**`mapToLegacyState(lifecycle: SessionLifecycleState, execution?: ExecutionState)` (L170–192)**
Inverse mapping: new state model → legacy `SessionState`. Falls back to `SessionState.READY` when `lifecycle` is `ACTIVE` but `execution` is undefined.

---

### Architectural Notes
- **Dual-state model**: `DebugSession` carries both old `state` and new `sessionLifecycle`/`executionState` for backward compatibility during migration.
- **`mapLegacyState`/`mapToLegacyState`** serve as the bridge between legacy consumers and new state logic.
- `MOCK` language in `DebugLanguage` supports test adapters without requiring a real runtime.
- `GenericAttachConfig` uses an index signature (`[key: string]: unknown`) enabling safe spread of language-specific properties without type errors.