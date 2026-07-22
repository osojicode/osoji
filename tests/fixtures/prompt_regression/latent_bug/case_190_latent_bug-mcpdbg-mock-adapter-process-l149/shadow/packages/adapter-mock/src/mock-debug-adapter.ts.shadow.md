# packages\adapter-mock\src\mock-debug-adapter.ts
@source-hash: 6d38806a8f889340
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:26Z

## Mock Debug Adapter (`mock-debug-adapter.ts`)

### Purpose
Implements `IDebugAdapter` for testing/simulation purposes. Provides a fully in-process mock of a DAP-compatible debug adapter without requiring external executables or network connections. Used as a test double or demo adapter for the `@debugmcp` framework.

---

### Key Exports

#### `MockAdapterConfig` interface (L36–43)
Optional config for the mock adapter:
- `connectionDelay?: number` — milliseconds to delay `connect()` (default: 50)
- `supportedFeatures?: DebugFeature[]` — which DAP features to advertise (default: `CONDITIONAL_BREAKPOINTS`, `FUNCTION_BREAKPOINTS`, `VARIABLE_PAGING`, `SET_VARIABLE`)

#### `MockErrorScenario` enum (L48–52)
Controls simulated failure paths:
- `NONE` — normal operation
- `EXECUTABLE_NOT_FOUND` — `validateEnvironment()` returns invalid
- `CONNECTION_TIMEOUT` — `connect()` throws `AdapterError`

#### `MockDebugAdapter` class (L110–487)
Extends `EventEmitter`, implements `IDebugAdapter`.

**Fields:**
- `language = DebugLanguage.MOCK` (L111)
- `name = 'Mock Debug Adapter'` (L112)
- `state: AdapterState` (private, L114)
- `currentThreadId: number | null` (private, L119)
- `connected: boolean` (private, L120)
- `errorScenario: MockErrorScenario` (private, L123)

---

### Methods

| Method | Lines | Notes |
|---|---|---|
| `constructor(dependencies, config?)` | L125–137 | Stores deps, applies defaults |
| `initialize()` | L141–161 | Validates env → `READY`; throws on failure |
| `dispose()` | L163–168 | Resets all state, emits `'disposed'` |
| `getState()` | L172–174 | Returns current `AdapterState` |
| `isReady()` | L176–179 | True if `READY`, `CONNECTED`, or `DEBUGGING` |
| `getCurrentThreadId()` | L182–184 | Returns tracked thread ID |
| `transitionTo(newState)` | L186–199 | Enforces `VALID_TRANSITIONS`; emits `'stateChanged'` |
| `validateEnvironment()` | L203–222 | Returns invalid if `EXECUTABLE_NOT_FOUND` scenario set |
| `getRequiredDependencies()` | L224–227 | Returns `[]` (no dependencies) |
| `resolveExecutablePath(preferred?)` | L231–237 | Returns `preferred` or `process.execPath` |
| `getDefaultExecutableName()` | L239–241 | Returns `'node'` |
| `getExecutableSearchPaths()` | L243–245 | Returns `PATH` entries |
| `buildAdapterCommand(config)` | L249–295 | Builds node command for `mock-adapter-process.js`/`.cjs`; uses `import.meta.url` with fallback to CWD resolution |
| `getAdapterModuleName()` | L297–299 | Returns `'mock-adapter'` |
| `getAdapterInstallCommand()` | L301–303 | Returns echo no-op |
| `transformLaunchConfig(config)` | L307–314 | Merges with `type: 'mock'`, `request: 'launch'` |
| `getDefaultLaunchConfig()` | L316–323 | Returns `stopOnEntry: false`, `justMyCode: true` |
| `sendDapRequest(command, args?)` | L327–338 | Logs request, returns `{}` — actual communication delegated to ProxyManager |
| `handleDapEvent(event)` | L340–358 | Updates thread/state on `stopped`, `continued`, `terminated`, `exited`; re-emits event |
| `handleDapResponse(_response)` | L360–363 | No-op |
| `connect(host, port)` | L367–388 | Optional delay, throws on `CONNECTION_TIMEOUT` scenario, transitions to `CONNECTED` |
| `disconnect()` | L390–395 | Resets connected/threadId, transitions to `DISCONNECTED` |
| `isConnected()` | L397–399 | Returns `this.connected` |
| `getInstallationInstructions()` | L403–405 | Returns built-in message |
| `getMissingExecutableError()` | L407–409 | Returns fallback message |
| `translateErrorMessage(error)` | L411–416 | Humanizes `ENOENT` errors |
| `supportsFeature(feature)` | L420–422 | Checks configured features list |
| `getFeatureRequirements(feature)` | L424–436 | Returns version requirement for `CONDITIONAL_BREAKPOINTS` |
| `getCapabilities()` | L438–477 | Returns full `AdapterCapabilities` object |
| `setErrorScenario(scenario)` | L484–486 | Test hook to inject error scenarios |

---

### State Machine (`VALID_TRANSITIONS`, L59–105)
Intentionally permissive to match real adapter behavior (comment at L56–57). Key non-obvious transitions:
- `UNINITIALIZED` → `DEBUGGING` (direct, no initialization required)
- `CONNECTED` → `CONNECTED` (idempotent)
- `DEBUGGING` → `DEBUGGING` (idempotent)
- `ERROR` → `READY` or `DISCONNECTED` (recovery paths)

---

### Adapter Process Path Resolution (L249–295)
`buildAdapterCommand` uses three-tiered resolution:
1. `import.meta.url` → `mock-adapter-process.js` in same directory
2. Fallback to `.cjs` variant (npx bundle scenario)
3. Exception catch fallback → `process.cwd()/packages/adapter-mock/dist/mock-adapter-process.js`

---

### DAP Event Handling (L340–358)
- `stopped` event: sets `currentThreadId`, transitions to `DEBUGGING`
- `continued` event: transitions to `DEBUGGING`
- `terminated`/`exited`: clears thread ID; transitions to `CONNECTED` if still connected, else `DISCONNECTED`
- All events re-emitted on EventEmitter as `event.event` name with `event.body`

---

### Dependencies
- `EventEmitter` from Node.js `events`
- `@vscode/debugprotocol` for DAP types
- `@debugmcp/shared` for all adapter interfaces and enums
- `path`, `fs`, `url` for adapter process path resolution

---

### Architectural Notes
- `sendDapRequest` always returns `{}` — the mock relies on `ProxyManager` for actual DAP communication (L331–337)
- `dependencies.logger` is accessed optionally with `?.` throughout — logger is not required
- `setErrorScenario()` is a test-only hook not part of `IDebugAdapter` interface