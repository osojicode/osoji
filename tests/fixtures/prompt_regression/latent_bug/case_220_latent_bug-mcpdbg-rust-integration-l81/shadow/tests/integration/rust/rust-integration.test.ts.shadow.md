# tests\integration\rust\rust-integration.test.ts
@source-hash: 6bd35e21633d955d
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:45Z

## Integration Tests for Rust Adapter

Integration test suite verifying the Rust debug adapter lifecycle through `SessionManager`. Tests run sequentially (shared `sessionId` state across `it` blocks) and require the `@debugmcp/shared` package's `DebugLanguage.RUST` enum value.

### Test Suite: `Rust Adapter Integration` (L11–88)

**Setup/Teardown:**
- `beforeAll` (L15–30): Instantiates `SessionManager` with production dependencies (debug log level, temp log file). Config uses OS temp dir for session logs, sets `stopOnEntry: true` and `justMyCode: true` as default DAP launch args.
- `afterAll` (L32–34): Calls `sessionManager.closeAllSessions()` to clean up any open sessions.

**Test Cases (sequential, stateful):**

| Test | Lines | Description |
|------|-------|-------------|
| `should create a Rust debug session` | L36–47 | Creates session with `DebugLanguage.RUST`, asserts `session.language` and `session.name`, captures `sessionId` for subsequent tests |
| `should verify Rust session persists after creation` | L49–56 | Retrieves session by `sessionId` via `sessionManager.getSession()`, confirms it still exists with correct language |
| `should queue breakpoint in Rust source file` | L58–79 | Attempts `setBreakpoint` on `examples/rust/hello_world/src/main.rs` line 5; wrapped in try/catch — failure is expected without a compiled Rust binary. Checks `breakpoint.verified` flag. |
| `should close the Rust session` | L81–87 | Calls `closeSession(sessionId)`, asserts return value is `true`, confirms `getSession` returns `undefined` after close |

### Key Dependencies
- `SessionManager` from `src/session/session-manager.js` — core orchestrator for debug sessions
- `createProductionDependencies` from `src/container/dependencies.js` — DI factory wiring real adapters
- `DebugLanguage` from `@debugmcp/shared` — enum/discriminant for language selection

### Architectural Notes
- Tests share mutable `sessionId` variable (L13), making ordering critical; vitest runs `it` blocks in declaration order within a `describe`.
- The breakpoint test (L58–79) is intentionally resilient — it neither skips formally (no `test.skip`) nor fails hard when a compiled binary is absent. This makes it a "soft" integration test.
- No compiled Rust project or active DAP server is required for the first two and last tests; only session metadata operations are verified.