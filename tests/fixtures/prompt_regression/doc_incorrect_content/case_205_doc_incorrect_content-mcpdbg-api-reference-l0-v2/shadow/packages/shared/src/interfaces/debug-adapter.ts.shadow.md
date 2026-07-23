# packages\shared\src\interfaces\debug-adapter.ts
@source-hash: cd6bc81887f8ba51
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:58Z

## Core Debug Adapter Interface

Defines the foundational contract (`IDebugAdapter`) and all supporting types for multi-language debug adapter implementations. Every language-specific debug adapter (Python, Node.js, Go, Ruby, etc.) must implement `IDebugAdapter`. This is a pure type/interface file — no runtime logic beyond the `AdapterError` class.

---

### Primary Interface: `IDebugAdapter` (L24–236)
Extends `EventEmitter`. All language adapters implement this contract.

**Readonly identity properties:**
- `language: DebugLanguage` — discriminant for the adapter's target language
- `name: string` — human-readable name (e.g., "Python Debug Adapter")

**Lifecycle (required):**
- `initialize(): Promise<void>` (L33) — set up adapter, validate environment
- `dispose(): Promise<void>` (L38) — tear down resources

**State (required):**
- `getState(): AdapterState` (L45)
- `isReady(): boolean` (L50)
- `getCurrentThreadId(): number | null` (L55)

**Environment validation (required):**
- `validateEnvironment(executablePath?: string): Promise<ValidationResult>` (L64) — accepts optional user-specified interpreter
- `getRequiredDependencies(): DependencyInfo[]` (L69)

**Executable management (required):**
- `resolveExecutablePath(preferredPath?: string): Promise<string>` (L77)
- `getDefaultExecutableName(): string` (L83) — e.g., `'python'`, `'node'`, `'go'`
- `getExecutableSearchPaths(): string[]` (L88)

**Adapter configuration (required):**
- `buildAdapterCommand(config: AdapterConfig): AdapterCommand` (L95)
- `getAdapterModuleName(): string` (L101) — e.g., `'debugpy.adapter'`
- `getAdapterInstallCommand(): string` (L107) — e.g., `'pip install debugpy'`

**Adapter launch barrier (optional):**
- `createLaunchBarrier?(command: string, args?: unknown): AdapterLaunchBarrier | undefined` (L113) — customizes ProxyManager coordination for fire-and-forget launches

**Debug configuration (required):**
- `transformLaunchConfig(config: GenericLaunchConfig): Promise<LanguageSpecificLaunchConfig>` (L123) — async since 2.1.0 to support build steps (e.g., Rust compilation)
- `getDefaultLaunchConfig(): Partial<GenericLaunchConfig>` (L128)

**Attach support (all optional):**
- `supportsAttach?(): boolean` (L134)
- `supportsDetach?(): boolean` (L140)
- `usesDirectConnectForAttach?(): boolean` (L149) — `true` means adapter connects to already-listening DAP server (e.g., rdbg `--open`) without spawning adapter process
- `transformAttachConfig?(config: GenericAttachConfig): LanguageSpecificAttachConfig` (L157)
- `getDefaultAttachConfig?(): Partial<GenericAttachConfig>` (L164)

**DAP protocol (required):**
- `sendDapRequest<T extends DebugProtocol.Response>(command: string, args?: unknown): Promise<T>` (L171)
- `handleDapEvent(event: DebugProtocol.Event): void` (L179)
- `handleDapResponse(response: DebugProtocol.Response): void` (L184)

**Connection (required):**
- `connect(host: string, port: number): Promise<void>` (L191)
- `disconnect(): Promise<void>` (L196)
- `isConnected(): boolean` (L201)

**Error handling (required):**
- `getInstallationInstructions(): string` (L208)
- `getMissingExecutableError(): string` (L213)
- `translateErrorMessage(error: Error): string` (L218)

**Feature support (required):**
- `supportsFeature(feature: DebugFeature): boolean` (L225)
- `getFeatureRequirements(feature: DebugFeature): FeatureRequirement[]` (L230)
- `getCapabilities(): AdapterCapabilities` (L235)

---

### Enums

**`AdapterState`** (L243–251): `UNINITIALIZED | INITIALIZING | READY | CONNECTED | DEBUGGING | DISCONNECTED | ERROR`

**`DebugFeature`** (L336–357): Full DAP feature set — conditional breakpoints, function breakpoints, exception breakpoints, variable paging, evaluate for hovers, set variable/expression, data breakpoints, disassemble, terminate/restart threads, delayed stack trace loading, loaded sources, log points, step back, reverse debugging, step-in targets.

**`AdapterErrorCode`** (L444–467): Categorized into environment errors (`ENVIRONMENT_INVALID`, `EXECUTABLE_NOT_FOUND`, `ADAPTER_NOT_INSTALLED`, `INCOMPATIBLE_VERSION`), connection errors (`CONNECTION_FAILED`, `CONNECTION_TIMEOUT`, `CONNECTION_LOST`), protocol errors (`INVALID_RESPONSE`, `UNSUPPORTED_OPERATION`), runtime errors (`DEBUGGER_ERROR`, `SCRIPT_NOT_FOUND`, `PERMISSION_DENIED`), and generic (`UNKNOWN_ERROR`).

---

### Supporting Interfaces

| Interface | Lines | Purpose |
|---|---|---|
| `ValidationResult` | L256–260 | Result of `validateEnvironment`: `valid`, `errors[]`, `warnings[]` |
| `ValidationError` | L265–269 | `code`, `message`, `recoverable` |
| `ValidationWarning` | L274–277 | `code`, `message` |
| `DependencyInfo` | L282–287 | Dependency descriptor; `version?`, `installCommand?` optional |
| `AdapterCommand` | L292–296 | `command`, `args: string[]`, `env?: Record<string,string>` |
| `AdapterConfig` | L301–310 | Full config for `buildAdapterCommand`: session, executable, host/port, log dir, script, `launchConfig` |
| `GenericLaunchConfig` | L315–322 | Language-agnostic: `stopOnEntry?`, `justMyCode?`, `env?`, `cwd?`, `args?` |
| `LanguageSpecificLaunchConfig` | L327–330 | Extends `GenericLaunchConfig` with `[key: string]: unknown` index signature |
| `FeatureRequirement` | L362–366 | `type: 'dependency' \| 'version' \| 'configuration'`, `description`, `required` |
| `AdapterCapabilities` | L371–411 | Full DAP capabilities mirror — ~30 optional boolean flags plus `exceptionBreakpointFilters`, `additionalModuleColumns`, `completionTriggerCharacters`, `supportedChecksumAlgorithms` |
| `ExceptionBreakpointFilter` | L416–423 | `filter`, `label`, `description?`, `default?`, `supportsCondition?`, `conditionDescription?` |
| `AdapterEvents` | L474–493 | Event map for the `EventEmitter`: DAP events (`stopped`, `continued`, `terminated`, `exited`, `thread`, `output`, `breakpoint`, `module`), lifecycle events (`initialized`, `connected`, `disconnected`, `error`), `stateChanged(oldState, newState)` |
| `ConfigMigration` | L500–509 | Migration helper: `migratePythonConfig`, `needsMigration` — assists transitioning Python-specific configs to generic format |

---

### Concrete Class: `AdapterError` (L430–439)
Extends `Error`. Sets `this.name = 'AdapterError'`. Constructor: `(message: string, code: AdapterErrorCode, recoverable: boolean = false)`. The `code` and `recoverable` fields are `public`.

---

### Key Design Notes
- `IDebugAdapter` extends `EventEmitter` directly — implementations must also call `EventEmitter` constructor
- `transformLaunchConfig` is async (since 2.1.0) to support languages that require build steps before launch
- Attach-related methods are all optional (`?`) — query `supportsAttach()` before calling `transformAttachConfig`/`getDefaultAttachConfig`
- `usesDirectConnectForAttach` controls whether ProxyManager builds an adapter command or instead uses a direct TCP connect for attach sessions
- `AdapterCapabilities` closely mirrors the DAP spec's `Capabilities` object, allowing direct passthrough to DAP clients
- `ConfigMigration` interface supports legacy Python config migration and is decoupled from `IDebugAdapter`
