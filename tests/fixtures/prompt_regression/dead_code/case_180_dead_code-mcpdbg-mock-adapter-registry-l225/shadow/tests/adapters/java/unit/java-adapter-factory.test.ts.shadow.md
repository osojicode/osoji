# tests\adapters\java\unit\java-adapter-factory.test.ts
@source-hash: 2820cc513484748a
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:56Z

## Overview
Unit tests for `JavaAdapterFactory` and `JavaDebugAdapter` from `@debugmcp/adapter-java`. Validates factory creation, metadata correctness, and environment validation logic (Java availability, version checks, JDI bridge presence, platform info).

## Test Structure

### Mock Setup (L8–16)
- `child_process.spawn` is mocked via `vi.mock` with `importOriginal` pattern to preserve other exports (L8–14).
- `mockSpawn` (L16) is the typed mock reference used in individual test cases.

### `createMockDependencies` (L18–47)
Helper factory returning a full `AdapterDependencies` stub:
- `fileSystem`: all methods are no-ops (returns empty/false/undefined)
- `logger`: all methods are `vi.fn()` spies
- `environment`: delegates to real `process.env` and `process.cwd()`

### Test Suite: `JavaAdapterFactory` (L49–208)

#### `createAdapter` (L62–72)
- Verifies `factory.createAdapter(deps)` returns a `JavaDebugAdapter` instance (L63–66)
- Verifies `adapter.language === DebugLanguage.JAVA` (L68–71)

#### `getMetadata` (L74–89)
- Checks `language`, `displayName` (`'Java'`), `version` (`'0.2.0'`), `description` contains `'JDI'`, `fileExtensions` contains `'.java'` (L75–83)
- Checks `documentationUrl` contains `'github.com'` (L85–88)

#### `validate` (L91–207)
Each test case uses `mockSpawn` to simulate a subprocess emitting stderr/stdout and exit events via `process.nextTick`.

| Test | Spawn behavior | Expected outcome |
|---|---|---|
| Java available (L92–112) | stderr: OpenJDK 17.0.1, exit 0 | `valid=true`, no errors, `details.javaPath` defined |
| Java not found (L114–130) | emit `error` event (ENOENT), `PATH=''`, `JAVA_HOME=undefined` | `valid=false`, errors present |
| JDI bridge warning (L132–149) | exit 0, Java 17 | warning check is optional/env-dependent; just verifies boolean result |
| Platform info (L151–168) | exit 0, Java 17 | `details.platform`, `details.arch`, `details.timestamp` populated |
| Version below 21 (L170–188) | Java 17.0.1 | `valid=true`, warning includes `'Java 21+ recommended'`, `details.javaVersion='17.0.1'` |
| Version 21+ (L190–207) | Java 21.0.1 | `valid=true`, no `'Java 21+ recommended'` warning |

## Key Behavioral Contracts Tested
- `validate()` result shape: `{ valid, errors, warnings?, details? }` where `details` includes `javaPath`, `javaVersion`, `platform`, `arch`, `timestamp`
- Java 21 is the recommended minimum; versions below emit a warning but remain valid
- Java unavailability (ENOENT) produces `valid=false`
- JDI bridge absence may produce a warning (environment-dependent, softly asserted at L147–148)

## Dependencies
- `@debugmcp/adapter-java`: `JavaAdapterFactory`, `JavaDebugAdapter`
- `@debugmcp/shared`: `AdapterDependencies` (type), `DebugLanguage` (enum)
- `child_process.spawn`: mocked to control subprocess behavior
- `vitest`: `describe`, `it`, `expect`, `beforeEach`, `afterEach`, `vi`
