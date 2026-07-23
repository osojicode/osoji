# packages\adapter-rust\src\index.ts
@source-hash: 4854f85903b60a77
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:31:57Z

## Overview

Barrel/entry-point module for the `@debugmcp/adapter-rust` package. Re-exports all public API symbols from internal submodules to provide a unified import surface for consumers of the Rust debug adapter.

## Exports

### Classes
- **`RustDebugAdapter`** (L9) — Core debug adapter implementation. Sourced from `./rust-debug-adapter.js`.
- **`RustAdapterFactory`** (L10) — Factory for creating `RustDebugAdapter` instances. Sourced from `./rust-adapter-factory.js`.

### Functions
- **`resolveCodeLLDBPath`** (L11) — Resolves the filesystem path to the CodeLLDB debugger binary. Sourced from `./utils/rust-utils.js`.
- **`checkCargoInstallation`** (L11) — Checks whether Cargo (Rust's package manager) is installed and accessible. Sourced from `./utils/rust-utils.js`.
- **`resolveCargoProject`** (L12) — Resolves metadata/structure of a Cargo project. Sourced from `./utils/cargo-utils.js`.
- **`getCargoTargets`** (L12) — Retrieves build targets defined in a Cargo project. Sourced from `./utils/cargo-utils.js`.
- **`resolveCodeLLDBExecutable`** (L13) — Resolves the CodeLLDB executable (may differ from `resolveCodeLLDBPath` in resolution strategy). Sourced from `./utils/codelldb-resolver.js`.
- **`detectBinaryFormat`** (L14) — Detects the binary format (e.g., ELF, Mach-O, PE) of a compiled artifact. Sourced from `./utils/binary-detector.js`.

### Types
- **`BinaryInfo`** (L15) — Type describing binary format metadata. Type-only export from `./utils/binary-detector.js`.

## Architecture Notes
- This is a pure barrel file — no logic lives here; all implementations are in submodules under `src/`.
- The package targets MCP (Model Context Protocol) debugger infrastructure and uses CodeLLDB as the underlying debug engine for Rust.
- Utility concerns are cleanly separated: `rust-utils` for toolchain checks, `cargo-utils` for project/target resolution, `codelldb-resolver` for executable discovery, `binary-detector` for artifact inspection.
