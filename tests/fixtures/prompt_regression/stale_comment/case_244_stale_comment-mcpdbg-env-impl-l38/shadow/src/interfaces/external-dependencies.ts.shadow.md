# src\interfaces\external-dependencies.ts
@source-hash: e904edcd18ba7261
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:33:02Z

## External Dependency Interfaces

Defines the full set of injectable dependency interfaces used for decoupling core logic from Node.js built-ins and external libraries (fs-extra, child_process, net). Enables mocking in tests without changing implementation code.

---

### Interfaces

#### `IFileSystem` (L17–36)
Abstracts both standard `fs` and `fs-extra` methods. All async variants return `Promise`; sync variants (`ensureDirSync`, `existsSync`) are synchronous. Methods:
- `readFile`, `writeFile`, `exists`, `mkdir`, `readdir`, `stat`, `unlink`, `rmdir` — standard fs ops
- `ensureDir`, `ensureDirSync`, `pathExists`, `existsSync`, `remove`, `copy`, `outputFile` — fs-extra extensions

`stat` returns `fs.Stats` (imported from `'fs'`).

#### `IChildProcess` (L42–50)
Extends `EventEmitter` (from `'events'`). Mirrors Node.js `ChildProcess`:
- `pid?: number`, `killed: boolean`
- `kill(signal?): boolean`, `send(message): boolean`
- `stdin`, `stdout`, `stderr` streams (nullable)

#### `IProcessManager` (L56–59)
Factory for process operations:
- `spawn(command, args?, options?)` → `IChildProcess` (uses `SpawnOptions` from `'child_process'`)
- `exec(command)` → `Promise<{ stdout, stderr }>`

#### `INetworkManager` (L65–68)
Network utility abstraction:
- `createServer()` → `IServer`
- `findFreePort()` → `Promise<number>`

#### `IServer` (L74–79)
Extends `EventEmitter`. Mirrors `net.Server`:
- `listen(port, callback?)`, `close(callback?)`, `address()`, `unref()` — all return `this` where chainable

#### `ILogger` (L85–90)
Standard four-level logger: `info`, `error`, `debug`, `warn`. Each accepts `message: string` and optional `meta: unknown`.

#### `IProxyManagerFactory` (L95–97)
Single-method factory:
- `create(adapter?)` → `IProxyManager` (from `'../proxy/proxy-manager.js'`)
- `adapter` is typed as `IDebugAdapter` (from `'@debugmcp/shared'`)

#### `IEnvironment` (L103–107)
Environment variable abstraction:
- `get(key)` → `string | undefined`
- `getAll()` → `Record<string, string | undefined>`
- `getCurrentWorkingDirectory()` → `string`

#### `IDependencies` (L112–118)
Aggregate DI container shape combining: `fileSystem`, `processManager`, `networkManager`, `logger`, `environment`. Used as the canonical full dependency bundle.

#### `PartialDependencies` (L124)
Type alias: `Partial<IDependencies>`. Allows components to declare only the subset of dependencies they use.

#### `ILoggerFactory` (L129–131)
- `createLogger(name, options?)` → `ILogger`

#### `IChildProcessFactory` (L133–135)
- `createChildProcess()` → `IChildProcess`

---

### Architecture Notes
- All interfaces are pure TypeScript — no runtime validation.
- Designed for constructor injection; implementations are provided by adapter-layer classes.
- `IProxyManagerFactory` bridges into the proxy subsystem, with `IDebugAdapter` typed from the shared package (`@debugmcp/shared`).
- `IChildProcessFactory` and `IProxyManagerFactory` are supplementary factory interfaces not included in `IDependencies` — callers must inject these separately if needed.
