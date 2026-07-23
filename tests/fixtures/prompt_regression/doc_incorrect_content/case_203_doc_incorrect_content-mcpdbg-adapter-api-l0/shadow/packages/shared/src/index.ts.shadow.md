# packages\shared\src\index.ts
@source-hash: 4de23fc736bf38e6
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:10Z

## `packages/shared/src/index.ts` — Public API Barrel

This is the top-level barrel/entry-point for the `@debugmcp/shared` package. It re-exports all public types, enums, classes, and utilities from sub-modules, forming the complete public API surface that other packages in the MCP Debugger ecosystem consume.

---

### Purpose
Aggregates and re-exports the core contracts (interfaces, types, enums, classes, utilities) that enable language-specific debug adapters to integrate with the main MCP Debugger. Nothing is defined here — everything is forwarded.

---

### Re-export Groups

#### Debug Adapter Interfaces (L14–55)
Source: `./interfaces/debug-adapter.js`
- **Types (L14–42):** `IDebugAdapter`, `ValidationResult`, `ValidationError`, `ValidationWarning`, `DependencyInfo`, `AdapterConfig`, `AdapterCommand`, `AdapterCapabilities`, `GenericLaunchConfig`, `LanguageSpecificLaunchConfig`, `FeatureRequirement`, `ExceptionBreakpointFilter`, `AdapterEvents`, `ConfigMigration`
- **Values (L45–55):** `AdapterState` (enum), `DebugFeature` (enum), `AdapterError` (class), `AdapterErrorCode` (enum)

#### Adapter Registry Interfaces (L57–90)
Source: `./interfaces/adapter-registry.js`
- **Types (L57–75):** `IAdapterRegistry`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `AdapterInfo`, `AdapterRegistryConfig`, `FactoryValidationResult`, `AdapterFactoryMap`, `ActiveAdapterMap`
- **Values (L77–90):** `BaseAdapterFactory` (class), `AdapterNotFoundError`, `FactoryValidationError`, `DuplicateRegistrationError` (error classes), `isAdapterFactory`, `isAdapterRegistry` (type guards)

#### External Dependencies Interfaces (L92–112)
Source: `./interfaces/external-dependencies.js`
- **Types:** `IFileSystem`, `IChildProcess`, `IProcessManager`, `INetworkManager`, `IServer`, `ILogger`, `IProxyManager`, `IProxyManagerFactory`, `IEnvironment`, `IDependencies`, `PartialDependencies`, `ILoggerFactory`, `IChildProcessFactory`

#### Process Interfaces (L114–123)
Source: `./interfaces/process-interfaces.js`
- **Types:** `IProcess`, `IProcessOptions`, `IProxyProcessLauncher`, `IProxyProcess`

#### Models (L125–160)
Source: `./models/index.js`
- **Types (L128–146):** `CustomLaunchRequestArguments`, `GenericAttachConfig`, `LanguageSpecificAttachConfig`, `SessionConfig`, `Breakpoint`, `DebugSession`, `DebugSessionInfo`, `Variable`, `StackFrame`, `DebugLocation`
- **Values (L149–160):** `DebugLanguage`, `SessionLifecycleState`, `ExecutionState`, `SessionState`, `ProcessIdentifierType` (enums); `mapLegacyState`, `mapToLegacyState` (functions)

#### Factories (L162–164)
Source: `./factories/adapter-factory.js`
- **Values:** `AdapterFactory` (class)

#### Adapter Policies (L166–184)
Per-language policy implementations (class values) and shared interface types:
- **Types (L167–174):** `AdapterPolicy`, `ChildSessionStrategy`, `AdapterSpecificState`, `CommandHandling`, `AdapterSpawnPayload`, `AdapterSpawnConfig`
- **Values (L175–184):** `DefaultAdapterPolicy`, `JsDebugAdapterPolicy`, `PythonAdapterPolicy`, `RubyAdapterPolicy`, `RustAdapterPolicy`, `GoAdapterPolicy`, `JavaAdapterPolicy`, `DotnetAdapterPolicy`, `MockAdapterPolicy`, `getPolicyForLanguage`

#### DAP Client Behavior (L186–192)
Source: `./interfaces/dap-client-behavior.js`
- **Types:** `DapClientBehavior`, `DapClientContext`, `ReverseRequestResult`, `ChildSessionConfig`

#### Adapter Launch Barrier (L194–195)
Source: `./interfaces/adapter-launch-barrier.js`
- **Types:** `AdapterLaunchBarrier`

#### FileSystem Abstraction (L197–199)
Source: `./interfaces/filesystem.js`
- **Types:** `FileSystem`
- **Values:** `NodeFileSystem` (class), `setDefaultFileSystem`, `getDefaultFileSystem` (functions)

#### VSCode Debug Protocol (L201–202)
Source: `@vscode/debugprotocol`
- **Types:** `DebugProtocol` (namespace/type re-export for consumer convenience)

#### Logging-Safety Utilities (L204–212)
Source: `./utils/env-sanitizer.js`
- **Values:** `sanitizeEnvForLogging`, `sanitizePayloadForLogging`, `sanitizeStderr`, `sanitizeStderrTail` — shared sanitization helpers preventing unsanitized child-process output from reaching logs

#### Line Buffer (L213)
Source: `./utils/line-buffer.js`
- **Values:** `LineBuffer` (class)

---

### Architectural Notes
- Strict separation of **type-only exports** (`export type { ... }`) vs. **value exports** (`export { ... }`) throughout. This is important for tree-shaking and for consumers using `isolatedModules`.
- Language-specific adapter policies (JS, Python, Ruby, Rust, Go, Java, .NET, Mock) are all individually exported, plus a `getPolicyForLanguage` dispatcher for dynamic lookup.
- `DebugProtocol` from `@vscode/debugprotocol` is forwarded as a convenience re-export so consumers don't need a direct dependency on that package.
- The logging-safety utilities are shared between the server and adapter packages — centralization here prevents code duplication and enforces consistent sanitization.