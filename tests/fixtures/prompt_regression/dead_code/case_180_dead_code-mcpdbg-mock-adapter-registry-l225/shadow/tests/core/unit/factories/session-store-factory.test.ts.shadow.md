# tests\core\unit\factories\session-store-factory.test.ts
@source-hash: cb235a9ee035117e
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:57Z

## Unit Tests: `session-store-factory.test.ts`

Unit test suite for the `SessionStoreFactory`, `MockSessionStoreFactory`, and `MockSessionStore` classes exported from `src/factories/session-store-factory.ts`. Organized into three nested `describe` blocks within the top-level `SessionStoreFactory` describe.

### Test Structure

**`SessionStoreFactory` suite (L12–146):**
- L13–33: Verifies `factory.create()` returns a `SessionStore` instance with all expected interface methods (`createSession`, `get`, `getOrThrow`, `set`, `update`, `updateState`, `remove`, `getAll`, `getAllManaged`, `has`, `size`, `clear`).
- L35–51: Confirms that multiple `create()` calls produce distinct, independent `SessionStore` instances (reference inequality).
- L53–69: Confirms factory has no internal instance-tracking state; each call returns a fresh instance.
- L71–95: Validates end-to-end functionality — creates a Python session with `CreateSessionParams`, verifies `session.id`, `session.name`, `session.language`, and store retrieval via `has`/`size`/`get`.
- L97–103: Type-level check that `SessionStoreFactory` satisfies `ISessionStoreFactory`.
- L105–118: Creates a DOTNET-language session and verifies `language`/`name`/`has` behavior.
- L120–145: State isolation — sessions created in separate store instances do not cross-contaminate; `has`/`size` remain independent.

**`MockSessionStoreFactory` suite (L148–237):**
- L149–161: `create()` returns a `MockSessionStore` that is also an instance of `SessionStore`; verifies `createSessionCalls` array exists.
- L163–179: `factory.createdStores` grows with each `create()` call; each entry is the exact instance returned.
- L181–195: Each `create()` returns a different `MockSessionStore` with its own separate `createSessionCalls` array.
- L197–212: Two `MockSessionStoreFactory` instances maintain independent `createdStores` arrays.
- L214–220: `MockSessionStoreFactory` satisfies `ISessionStoreFactory`.
- L222–236: All stores created in a loop are accessible via `factory.createdStores` in insertion order.

**`MockSessionStore` suite (L239–400):**
- L240–244: Inherits from `SessionStore` (dual `instanceof` check).
- L246–250: Assignable to `SessionStore` type.
- L252–255: Starts with empty `createSessionCalls` array.
- L257–278: Tracks each `createSession` call by appending `{ params }` to `createSessionCalls` in order, using both `DebugLanguage.PYTHON` and `DebugLanguage.MOCK`.
- L280–303: Tracking does not break base `SessionStore` functionality — session is still retrievable via `get`/`has`/`size`.
- L305–331: Independent tracking between two `MockSessionStore` instances; arrays are reference-unequal.
- L333–353: Tracks 5 sequential calls in correct order.
- L355–368: Minimal params (language only, no name) — auto-generated name matches `/^session-/` regex.
- L370–383: All 12 `SessionStore` methods remain callable on `MockSessionStore`.
- L385–399: Exact parameter capture including optional `executablePath` field.

### Key Contracts Verified
- `SessionStoreFactory.create()` → always a new `SessionStore`, no internal retention.
- `MockSessionStoreFactory.create()` → new `MockSessionStore` registered in `factory.createdStores`.
- `MockSessionStore.createSession(params)` → delegates to `SessionStore` AND appends `{ params }` to `createSessionCalls`.
- `DebugLanguage.PYTHON`, `DebugLanguage.DOTNET`, and `DebugLanguage.MOCK` are all used as session language discriminants.
- Auto-generated session names follow the pattern `/^session-/` (L367).

### Dependencies
- `vitest`: test runner (`describe`, `it`, `expect`).
- `../../../../src/factories/session-store-factory.js`: SUT — `SessionStoreFactory`, `MockSessionStoreFactory`, `MockSessionStore`, `ISessionStoreFactory`.
- `../../../../src/session/session-store.js`: `SessionStore` (base class), `CreateSessionParams` (param shape).
- `@debugmcp/shared`: `DebugLanguage` enum (`PYTHON`, `DOTNET`, `MOCK`).