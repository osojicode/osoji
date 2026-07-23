# tests\core\unit\server\server-language-discovery.test.ts
@source-hash: de2a06e26a445fc2
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:41Z

## Purpose
Unit tests for `DebugMcpServer`'s dynamic language discovery, metadata generation, and adapter registry integration. Specifically validates the `list_supported_languages`, `create_debug_session`, and `start_debugging` MCP tool handlers under various adapter registry configurations.

## Test Structure

### Top-level suite: `Server Language Discovery Tests` (L24–509)
Shared state:
- `debugServer: DebugMcpServer` — recreated in each test
- `mockServer` — fake MCP SDK `Server` instance (via `createMockServer`)
- `mockSessionManager` — fake `SessionManager` (via `createMockSessionManager`)
- `mockDependencies` — fake DI container (via `createMockDependencies`)
- `mockAdapterRegistry` — extended mock registry with discovery methods

### `beforeEach` (L31–55)
1. Calls `createMockDependencies()` → patches `createProductionDependencies` mock
2. Calls `createMockServer()` → patches `Server` constructor mock
3. Builds extended `mockAdapterRegistry` with:
   - `getSupportedLanguages` → `['python', 'mock']`
   - `listLanguages` (async) → `['python', 'mock']`
   - `listAvailableAdapters` (async) → array with `python` and `mock` adapter descriptors
   - `isLanguageSupported` → `true`
   - `create`, `register` stubs
4. Assigns registry to `mockDependencies.adapterRegistry`
5. Patches `SessionManager` with `createMockSessionManager(mockAdapterRegistry)`

## Sub-suites and Key Tests

### `JavaScript availability and metadata` (L61–98)
- **L62**: Verifies that when `listAvailableAdapters` returns a `javascript` entry with `installed: true`, `list_supported_languages` responds with:
  - `available[].language === 'javascript'`, `installed: true`, `package === '@debugmcp/adapter-javascript'`
  - `languages[].id === 'javascript'` with `displayName: 'JavaScript/TypeScript'`, `requiresExecutable: true`, `defaultExecutable: 'node'`

### `Ruby availability and metadata` (L100–138)
- **L101**: Verifies full exact-match shapes for ruby in both `available` and `languages` arrays:
  - `available`: `{ language, package, installed, description }`
  - `languages`: `{ id: 'ruby', displayName: 'Ruby', version: '1.0.0', requiresExecutable: true, defaultExecutable: 'ruby' }`

### `getSupportedLanguagesAsync` (L140–263)
- **L141**: Dynamic discovery path — `listLanguages` returns `['python', 'mock']` → `languages` metadata has exactly 2 entries; `listAvailableAdapters` is called.
- **L169**: Fallback path — `listLanguages` rejects → falls back to `getSupportedLanguages(['python', 'mock'])` → `languages` IDs = `['python', 'mock']`.
- **L193**: Undefined registry — `mockDependencies.adapterRegistry = undefined` → graceful degradation → `languages` IDs = `['python', 'mock']` (server defaults).
- **L215**: Empty registry responses → server uses defaults; result still contains `python` and `mock`.
- **L240**: Container mode — `vi.stubEnv('MCP_CONTAINER', 'true')`, `listLanguages` returns only `['mock']` → `installed` still contains `'python'` (injected by container logic).

### `getLanguageMetadata` (L265–319)
- **L266**: Metadata generated for discovered languages; response has `content.languages` or `content.languageMetadata`.
- **L287**: Unknown language `'unknown-language'` — included in `languages` metadata; `displayName` contains `'unknown'` (case-insensitive), `requiresExecutable: true`, `defaultExecutable` optionally equals `'unknown-language'`.

### `create_debug_session with language validation` (L322–393)
- **L323**: Valid language `python` → `mockSessionManager.createSession` called with `{ language: 'python', name: 'test-session', executablePath: undefined }`.
- **L355**: Unsupported language `'unsupported-language'` → tool call rejects with error containing `'unsupported-language'`.
- **L374**: Discovery failure + empty `getSupportedLanguages` → `create_debug_session` for `python` rejects.

### `start_debugging with language support validation` (L396–458)
- Nested `beforeEach` (L397–404) sets up `getSessionById` returning `{ id: 'session-123', language: 'python', state: { lifecycleState: 'READY' } }` and `startDebugging` resolving `{ success: true }`.
- **L406**: Session language `python` in discovered list → `start_debugging` resolves with `content.success` defined.
- **L429**: Session language `javascript` discovered dynamically → resolves with `content.success` defined.

### `adapter registry interaction edge cases` (L460–509)
- **L461**: Registry without `listLanguages` method → falls back gracefully; `languages` still contains `python` and `mock` (note: comment says "mock adapter registry still returns both" even though the inline registry only has `getSupportedLanguages(['python'])`).
- **L486**: `listLanguages` throws synchronously → caught; falls back to `getSupportedLanguages(['python', 'mock'])` → `languageIds` = `['python', 'mock']`.

## Key Dependencies
| Import | Role |
|---|---|
| `vitest` (L6) | Test runner — `describe`, `it`, `expect`, `beforeEach`, `afterEach`, `vi` |
| `@modelcontextprotocol/sdk/server/index.js` (L7) | `Server` — mocked at module level |
| `DebugMcpServer` from `src/server.js` (L8) | System under test |
| `SessionManager` from `src/session/session-manager.js` (L9) | Mocked; controls session operations |
| `createProductionDependencies` from `src/container/dependencies.js` (L10) | Mocked DI factory |
| `server-test-helpers.js` (L11–16) | `createMockDependencies`, `createMockServer`, `createMockSessionManager`, `getToolHandlers` |

## Mocking Strategy
- `vi.mock` at module-level for SDK, SessionManager, and dependencies (L19–22)
- `vi.mocked(X).mockImplementation/mockReturnValue` in `beforeEach` to wire mocks
- `getToolHandlers(mockServer)` extracts `callToolHandler` from the registered MCP tool handlers on the fake server
- Individual tests override registry methods via `vi.fn()` re-assignment

## Response Shape Assumptions
Tests parse `result.content[0].text` as JSON and expect:
- `content.languages` — array of `{ id, displayName, version?, requiresExecutable, defaultExecutable? }`
- `content.available` — array of `{ language, package, installed, description? }`
- `content.installed` — array of language ID strings (used in container test L259)
