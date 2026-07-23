# packages\adapter-python\src\python-adapter-factory.ts
@source-hash: b6711c9817ff24c7
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:39Z

## PythonAdapterFactory (L19-110)

Factory class implementing `IAdapterFactory` for creating Python debug adapter instances. This is the primary entry point for instantiating the Python debug adapter and performing environment validation before session creation.

### Key Class: `PythonAdapterFactory` (L19-110)
Implements `IAdapterFactory` from `@debugmcp/shared`. Three public methods:

#### `createAdapter(dependencies)` (L23-25)
Constructs and returns a `PythonDebugAdapter` instance, passing `AdapterDependencies` directly. Synchronous, no validation.

#### `getMetadata()` (L30-42)
Returns a static `AdapterMetadata` object describing the Python adapter:
- `language`: `DebugLanguage.PYTHON`
- `version`: `'2.0.0'`
- `minimumDebuggerVersion`: `'1.0.0'`
- `fileExtensions`: `['.py', '.pyw']`
- `documentationUrl`: points to GitHub docs
- `icon`: inline SVG base64 (Python logo, blue/yellow)

#### `validate()` (L47-91) — async
Performs 3-stage environment check returning `FactoryValidationResult`:
1. **Python executable detection** via `findPythonExecutable()` (L55) — failure pushes to `errors[]`
2. **Version check** via `getPythonVersion()` (L58) — requires Python ≥ 3.7; version below threshold pushes to `errors[]`; undetectable version pushes to `warnings[]`
3. **debugpy check** via private `checkDebugpyInstalled()` (L70) — missing debugpy pushes to `warnings[]` only (not an error), to accommodate virtualenv scenarios (see inline comment referencing issue #16)

`details` payload (L83-89) includes: `pythonPath`, `pythonVersion`, `pythonDetectionMethod: 'multi-strategy'`, `process.platform`, and ISO timestamp.

`valid` field (L80) is `true` iff `errors` array is empty.

#### `checkDebugpyInstalled(pythonPath)` (L96-110) — private async
Spawns a subprocess running `python -c 'import debugpy; print(debugpy.__version__)'`. Resolves `true` only if exit code is 0 AND stdout is non-empty. Errors (e.g., ENOENT) resolve to `false`. Uses `child.stdout?.on` (optional chaining on stdio pipe).

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage`
- `./python-debug-adapter.js`: `PythonDebugAdapter` (instantiated in `createAdapter`)
- `./utils/python-utils.js`: `findPythonExecutable`, `getPythonVersion`
- Node.js `child_process.spawn`: used in `checkDebugpyInstalled`

### Architectural Notes
- Validation is **non-blocking for debugpy** — missing debugpy in system Python is a warning, not an error, because users may have it in a virtualenv. This is an intentional design decision documented in the comment at L68-69.
- The `pythonDetectionMethod` field is hardcoded as `'multi-strategy'` (L86), indicating the actual strategy logic lives in `findPythonExecutable()` in python-utils.
- Version parsing (L60): splits version string on `.` and maps to `Number`; relies on `getPythonVersion` returning a dotted version string.