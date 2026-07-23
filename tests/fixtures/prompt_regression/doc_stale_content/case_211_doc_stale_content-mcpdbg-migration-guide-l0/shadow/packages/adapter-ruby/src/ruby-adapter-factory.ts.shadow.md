# packages\adapter-ruby\src\ruby-adapter-factory.ts
@source-hash: fffa236a59a74c4c
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:02Z

## RubyAdapterFactory (L17-83)

Factory class implementing `IAdapterFactory` for Ruby debug adapter integration. Responsible for creating `RubyDebugAdapter` instances, providing adapter metadata, and validating the Ruby debug environment (Ruby runtime + rdbg debugger availability).

### Key Class: `RubyAdapterFactory` (L17-83)

Implements `IAdapterFactory` interface from `@debugmcp/shared`. Three public methods:

- **`createAdapter(dependencies)`** (L18-20): Instantiates and returns a `RubyDebugAdapter` with the provided `AdapterDependencies`. Thin factory delegation.
- **`getMetadata()`** (L22-33): Returns static `AdapterMetadata` for the Ruby adapter — language discriminant `DebugLanguage.RUBY`, version `0.21.0`, minimum debugger version `1.7.0`, supported file extensions `['.rb', '.rake', '.gemspec']`, documentation URL.
- **`validate()`** (L35-82): Async environment validation. Sequentially checks:
  1. Ruby executable presence (`findRubyExecutable`) and version (`getRubyVersion`). Enforces Ruby >= 2.7; pushes error if below, warning if version indeterminate.
  2. rdbg executable presence (`findRdbgExecutable`) and version (`getRdbgVersion`). Pushes warning if version indeterminate.
  Returns `FactoryValidationResult` with `valid` flag, `errors[]`, `warnings[]`, and a `details` object containing resolved paths/versions, `process.platform`, and ISO timestamp.

### Dependencies
- `@debugmcp/shared`: `IDebugAdapter`, `IAdapterFactory`, `AdapterDependencies`, `AdapterMetadata`, `FactoryValidationResult`, `DebugLanguage`
- `./ruby-debug-adapter.js`: `RubyDebugAdapter` — the concrete adapter produced by this factory
- `./utils/ruby-utils.js`: `findRubyExecutable`, `getRubyVersion`, `findRdbgExecutable`, `getRdbgVersion` — environment probe utilities

### Validation Logic Constraints
- Ruby version check (L48-51): only `major` and `minor` are extracted; patch version is ignored.
- Both Ruby and rdbg checks are independent try/catch blocks — rdbg validation runs even if Ruby is not found.
- `valid` is `true` only when `errors` array is empty (L70); warnings do not affect validity.