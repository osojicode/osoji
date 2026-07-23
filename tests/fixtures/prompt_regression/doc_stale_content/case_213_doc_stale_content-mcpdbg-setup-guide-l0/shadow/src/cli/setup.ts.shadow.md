# src\cli\setup.ts
@source-hash: 59f1244f4df4904b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:47Z

## Purpose
Defines the CLI structure for the project using `commander`. Exports reusable option interfaces, handler type aliases, and setup functions that wire subcommands to handler callbacks. Intended to be composed by an entry-point file that provides concrete handler implementations.

## Key Exports

### Interfaces & Types
- **`StdioOptions` (L3-6)**: `{ logLevel?: string; logFile?: string }` — options for the `stdio` subcommand.
- **`SSEOptions` (L8-12)**: `{ port: string; logLevel?: string; logFile?: string }` — options for the `sse` subcommand.
- **`HttpOptions` (L14)**: Type alias for `SSEOptions`; used by the `http` subcommand.
- **`CheckRustBinaryOptions` (L16-18)**: `{ json?: boolean }` — options for the `check-rust-binary` subcommand.
- **`StdioHandler` (L20)**, **`SSEHandler` (L21)**, **`HttpHandler` (L22)**, **`CheckRustBinaryHandler` (L23-27)**: Async callback signatures for each subcommand action.

### Functions

#### `createCLI` (L29-38)
- **Signature**: `(name: string, description: string, version: string) => Command`
- Creates and returns a root `Command` with `.name()`, `.description()`, and `.version()` set. Entry point for constructing the CLI program object.

#### `setupStdioCommand` (L40-51)
- **Signature**: `(program: Command, handler: StdioHandler) => void`
- Registers the `stdio` subcommand (marked `isDefault: true`) with options: `--log-level` (default `'info'`), `--log-file`.
- **Side effect**: Sets `process.env.CONSOLE_OUTPUT_SILENCED = '1'` before invoking handler — ensures logger suppresses console output under bundling/stdio transport.

#### `setupSSECommand` (L53-65)
- **Signature**: `(program: Command, handler: SSEHandler) => void`
- Registers the deprecated `sse` subcommand with options: `--port` (default `'3001'`), `--log-level`, `--log-file`.
- Sets `process.env.CONSOLE_OUTPUT_SILENCED = '1'` to protect JS debugging transports.

#### `setupHttpCommand` (L67-79)
- **Signature**: `(program: Command, handler: HttpHandler) => void`
- Registers the `http` subcommand (recommended transport) with same options as `sse`.
- Sets `process.env.CONSOLE_OUTPUT_SILENCED = '1'` to protect spawned proxy IPC channels.

#### `setupCheckRustBinaryCommand` (L81-93)
- **Signature**: `(program: Command, handler: CheckRustBinaryHandler) => void`
- Registers `check-rust-binary` subcommand with positional argument `<binaryPath>` and `--json` flag (default `false`). Does **not** set `CONSOLE_OUTPUT_SILENCED`.

## Architectural Notes
- This file is a **pure setup/registration module** — no business logic, no direct I/O beyond `process.env` mutation.
- Handler injection pattern decouples CLI wiring from implementation, enabling testability.
- `HttpOptions` is a type alias of `SSEOptions` (L14), meaning they share identical option shapes; callers should treat them as the same runtime structure.
- `CONSOLE_OUTPUT_SILENCED` env var is set synchronously in the `action` callback before `await handler(...)`, ensuring the logger configuration happens before any async work.
- The `sse` subcommand description explicitly marks it as deprecated in favor of `http` (L56).