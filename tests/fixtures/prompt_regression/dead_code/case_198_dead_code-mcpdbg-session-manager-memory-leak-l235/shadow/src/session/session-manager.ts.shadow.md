# src\session\session-manager.ts
@source-hash: 4463ba7b8d3c461c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:06Z

## Session Manager (`src/session/session-manager.ts`)

### Purpose
Entry point and composition root for the debug session management system. Extends `SessionManagerOperations` with the concrete `handleAutoContinue` implementation, and re-exports all public types and classes from the session manager subsystem.

### Key Elements

#### `SessionManager` class (L28–35)
- Extends `SessionManagerOperations` (which in turn extends the core layer).
- Provides the sole concrete override: `handleAutoContinue(sessionId)` (L29–35).
  - Logs an info message, calls `this.continue(sessionId)` (inherited), and warns on failure.
  - This is the only piece of business logic defined here; all other session operations live in `SessionManagerOperations` or `SessionManagerCore`.

#### Re-exported types (L13–20)
From `session-manager-core.js`:
- `SessionManagerDependencies` — dependency-injection surface (logger, proxy factory, etc.)
- `SessionManagerConfig` — configuration shape for session manager construction
- `CustomLaunchRequestArguments` — extended DAP launch request arguments
- `DebugResult` — return type for debug operations

From `session-manager-operations.js`:
- `EvaluateResult` — return type for expression evaluation operations

#### Re-exported class (L23)
- `SessionManagerOperations` — re-exported for consumers needing direct access to the operations layer without the concrete `handleAutoContinue` binding.

### Architectural Role
This file is the **composition root** of a layered inheritance chain:
```
SessionManager (this file)
  └─ SessionManagerOperations (session-manager-operations.ts)
       └─ SessionManagerCore (session-manager-core.ts)
```
The split keeps core state/lifecycle, DAP operations, and the final concrete override in separate files. This file exists purely to close the abstract method `handleAutoContinue` and provide a unified import surface.

### Dependencies
- `SessionManagerOperations` from `./session-manager-operations.js` — base class providing all session operations and the abstract `handleAutoContinue` hook.
- Types only from `./session-manager-core.js` — no runtime dependency on the core module directly.

### Usage Pattern
Consumers should import `SessionManager` (the concrete class) and the associated types from this single module rather than reaching into the sub-modules directly.