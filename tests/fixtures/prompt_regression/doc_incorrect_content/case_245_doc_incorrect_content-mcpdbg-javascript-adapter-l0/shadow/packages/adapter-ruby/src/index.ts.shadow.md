# packages\adapter-ruby\src\index.ts
@source-hash: d5ab233d2d71a065
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:37Z

## Barrel/Entry Point for `packages/adapter-ruby`

This is the public API surface of the `adapter-ruby` package. It re-exports all externally consumable symbols from three internal modules.

### Re-exported Symbols

**From `./ruby-adapter-factory.js` (L1):**
- `RubyAdapterFactory` — Factory class responsible for creating Ruby debug adapter instances.

**From `./ruby-debug-adapter.js` (L2):**
- `RubyDebugAdapter` — Core debug adapter implementation for Ruby, likely implementing a DAP (Debug Adapter Protocol) interface.

**From `./utils/ruby-utils.js` (L3–11):**
- `findRubyExecutable` — Locates the Ruby executable on the system.
- `getRubyVersion` — Retrieves the version of the installed Ruby runtime.
- `findRdbgExecutable` — Locates the `rdbg` (Ruby Debugger) executable.
- `getRdbgVersion` — Retrieves the version of the installed `rdbg` tool.
- `getRubySearchPaths` — Returns filesystem paths to search for the Ruby executable.
- `getRdbgSearchPaths` — Returns filesystem paths to search for `rdbg`.
- `buildRdbgInvocation` — Constructs the command-line invocation arguments for launching `rdbg`.
- `RdbgInvocation` (type-only, L12) — TypeScript type describing the shape of an `rdbg` invocation configuration.

### Architectural Notes
- This file is a pure barrel module — no logic, only re-exports.
- Consumers of this package should import exclusively from this entry point.
- The `RdbgInvocation` type is exported via `export type`, meaning it is erased at runtime (compile-time only).
- The split between factory (`RubyAdapterFactory`), adapter (`RubyDebugAdapter`), and utilities (`ruby-utils`) follows a separation-of-concerns pattern common in DAP adapter packages.