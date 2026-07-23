# packages\shared\src\interfaces\external-dependencies.ts
@source-hash: 3ff72f45486aa1b5
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:52Z

## Purpose

Defines TypeScript interfaces for all external dependencies used in the codebase, enabling dependency injection, mocking, and testing without altering production implementations. Serves as the contract layer between business logic and external systems (filesystem, processes, network, logging, environment).

## Key Interfaces

### `IProxyManager` (L12–15)
Minimal interface for proxy lifecycle management. Only method: `dispose(): Promise<void>`. Used as the return type of `IProxyManagerFactory.create()`.

### `IFileSystem` (L21–40)
Mirrors `fs` + `fs-extra` APIs. Two groups:
- **Basic fs**: `readFile`, `writeFile`, `exists`, `mkdir`, `readdir`, `stat`, `unlink`, `rmdir`
- **fs-extra**: `ensureDir`, `ensureDirSync`, `pathExists`, `existsSync`, `remove`, `copy`, `outputFile`

`stat()` returns `Promise<Stats>` (Node.js `fs.Stats`).

### `IChildProcess` (L46–54)
Extends `EventEmitter`. Mirrors Node.js `ChildProcess`. Fields: `pid?`, `killed`, `stdin`/`stdout`/`stderr` streams, `kill(signal?)`, `send(message)`.

### `IProcessManager` (L60–63)
Abstracts process spawning:
- `spawn(command, args?, options?)` → `IChildProcess` (uses `SpawnOptions` from `child_process`)
- `exec(command)` → `Promise<{ stdout, stderr }>`

### `INetworkManager` (L69–72)
- `createServer()` → `IServer`
- `findFreePort()` → `Promise<number>`

### `IServer` (L78–83)
Extends `EventEmitter`. Mirrors `net.Server`. Methods: `listen`, `close`, `address`, `unref`. All chainable (return `this`). `address()` returns `{ port: number } | string | null`.

### `ILogger` (L89–94)
Standard four-level logger: `info`, `error`, `debug`, `warn`. Each accepts `message: string` and optional `meta?: unknown`.

### `IProxyManagerFactory` (L99–101)
Factory for creating `IProxyManager` instances. `create(adapter?: IDebugAdapter)` — adapter is optional; typed via imported `IDebugAdapter`.

### `IEnvironment` (L107–111)
- `get(key)` → `string | undefined` — single env var lookup
- `getAll()` → `Record<string, string | undefined>` — full env snapshot
- `getCurrentWorkingDirectory()` → `string`

### `IDependencies` (L116–122)
Aggregate DI container interface bundling all five core dependencies: `fileSystem`, `processManager`, `networkManager`, `logger`, `environment`.

### `PartialDependencies` (L128)
Type alias: `Partial<IDependencies>`. Allows components to declare only the subset of dependencies they require.

### `ILoggerFactory` (L133–135)
`createLogger(name, options?)` → `ILogger`. Supports named logger creation with optional config.

### `IChildProcessFactory` (L137–139)
`createChildProcess()` → `IChildProcess`. Factory for child process instances.

## Dependencies & Relationships
- `EventEmitter` from Node.js `events` — extended by `IChildProcess` and `IServer`
- `SpawnOptions` from Node.js `child_process` — parameter type in `IProcessManager.spawn`
- `Stats` from Node.js `fs` — return type in `IFileSystem.stat`
- `IDebugAdapter` from `./debug-adapter.js` — optional parameter in `IProxyManagerFactory.create`

## Architectural Notes
- Pure type file: no runtime code, no classes, no values — only interface and type alias definitions
- Acts as the central DI contract for the shared package; consumers implement or mock these interfaces
- `IDependencies` is the primary injection token; `PartialDependencies` supports incremental adoption
- `IChildProcess` and `IServer` extend `EventEmitter` structurally, ensuring event-based integration points remain testable
