# tests\core\unit\server\server-language-discovery.test.ts
@source-hash: ac2962a1cc1b0307
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:55Z

## Purpose
Unit tests for `DebugMcpServer`'s dynamic language discovery functionality, covering the `list_supported_languages` and `create_debug_session` MCP tool handlers, adapter registry integration, metadata generation, and fallback behavior.

## Test Structure

### Top-Level Suite: `Server Language Discovery Tests` (L24–509)
All tests share a common `beforeEach` (L31–55) that:
1. Creates mock dependencies via `createMockDependencies()` and injects via `createProductionDependencies` mock
2. Creates a `mockServer` via `createMockServer()` and injects via `Server` constructor mock
3. Constructs an extended `mockAdapterRegistry` (L39–50) with methods: `getSupportedLanguages`, `listLanguages`, `listAvailableAdapters`, `isLanguageSupported`, `create`, `register`
4. Creates `mockSessionManager` via `createMockSessionManager(mockAdapterRegistry)` and injects via `SessionManager` mock

### Describe Blocks

#### `JavaScript availability and metadata` (L61–98)
- Tests that when the registry dynamically reports `javascript`, the `list_supported_languages` tool returns `installed: true` in `available[]` and a rich metadata entry in `languages[]` with `displayName: 'JavaScript/TypeScript'`, `requiresExecutable: true`, `defaultExecutable: 'node'`

#### `Ruby availability and metadata` (L100–138)
- Tests that dynamically discovered `ruby` appears in both `available[]` and `languages[]` with exact shape: `{ id: 'ruby', displayName: 'Ruby', version: '1.0.0', requiresExecutable: true, defaultExecutable: 'ruby' }`

#### `getSupportedLanguagesAsync` (L140–263)
Five tests:
- **Dynamic discovery success** (L141–167): Returns languages from `listLanguages` + `listAvailableAdapters`; asserts `languageIds` length is 2 and `listAvailableAdapters` was called
- **Fallback on failure** (L169–191): When `listLanguages` rejects, falls back to `getSupportedLanguages` static list `['python', 'mock']`
- **Undefined registry** (L193–213): When `adapterRegistry` is `undefined`, tool still returns `['python', 'mock']` (server defaults)
- **Empty lists** (L215–238): When registry returns empty arrays, server falls back to defaults including `python` and `mock`
- **Container environment** (L240–262): With `MCP_CONTAINER=true` env var stubbed, even if registry only returns `['mock']`, the `installed` array still contains `python`

#### `getLanguageMetadata` (L265–319)
Two tests:
- **Metadata generation** (L266–285): Asserts `content.languages` or `content.languageMetadata` is defined
- **Unknown languages** (L287–319): When registry returns `'unknown-language'`, it appears in metadata; if metadata entry exists, `displayName.toLowerCase()` contains `'unknown'`, `requiresExecutable: true`, and `defaultExecutable` (if present) equals `'unknown-language'`

#### `create_debug_session with language validation` (L322–393)
Three tests:
- **Valid language** (L323–353): Asserts `createSession` called with `{ language: 'python', name: 'test-session', executablePath: undefined }`
- **Unsupported language** (L355–372): Expects tool handler to reject with error message containing `'unsupported-language'`
- **Discovery failure + empty list** (L374–393): When `listLanguages` rejects and `getSupportedLanguages` returns `[]`, session creation for `python` throws

#### `start_debugging with language support validation` (L396–458)
Nested `beforeEach` (L397–404) stubs `getSessionById` returning a python session in `READY` state and `startDebugging` resolving `{ success: true }`. Two tests:
- **Static language** (L406–427): `start_debugging` for `python` session; asserts `content.success` is defined
- **Dynamically discovered language** (L429–457): Session has `language: 'javascript'`, registry returns it; asserts `content.success` is defined

#### `adapter registry interaction edge cases` (L460–508)
Two tests:
- **Missing methods** (L461–484): Registry without `listLanguages`; result still contains `python` and `mock` (mock registry defaults)
- **Method exceptions** (L486–508): `listLanguages` throws synchronously; falls back to `getSupportedLanguages` returning `['python', 'mock']`

## Key Dependencies
- **`DebugMcpServer`** from `../../../../src/server.js` — the system under test
- **`SessionManager`** from `../../../../src/session/session-manager.js` — mocked
- **`createProductionDependencies`** from `../../../../src/container/dependencies.js` — mocked
- **`Server`** from `@modelcontextprotocol/sdk/server/index.js` — mocked
- **`getToolHandlers`** from `./server-test-helpers.js` — extracts registered MCP tool handler from `mockServer` for direct invocation

## MCP Tool Names Under Test
- `list_supported_languages` — primary focus; returns `{ languages[], available[], installed[] }`
- `create_debug_session` — secondary; validates language support
- `start_debugging` — secondary; validates session language

## Response Shape Expectations
The `list_supported_languages` tool response JSON shape (inferred from tests):
```typescript
{
  languages: Array<{ id: string, displayName: string, version?: string, requiresExecutable: boolean, defaultExecutable?: string }>,
  available: Array<{ language: string, package: string, installed: boolean, description?: string }>,
  installed: string[]
}
```

## Notable Patterns
- `vi.stubEnv('MCP_CONTAINER', 'true')` (L241) — environment variable injection for container test; no corresponding `vi.unstubAllEnvs()` in `afterEach` (only `vi.clearAllMocks()` at L58), which could leak across tests if test ordering matters
- Tests frequently re-declare `debugServer = new DebugMcpServer()` at the top of each `it` block rather than relying on `beforeEach`, making them self-contained but slightly redundant with the suite-level `beforeEach` setup
- The `mockAdapterRegistry.listAvailableAdapters` mock set in `beforeEach` (L43–46) returns `python` and `mock` by default; individual tests override it for specific scenarios