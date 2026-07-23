# tests\core\unit\session\models.test.ts
@source-hash: fe86be411c113a8e
@impl-hash: 3070d268ec6874c0
@generated: 2026-07-23T18:32:42Z

## Purpose
Unit tests for session model state mapping functions (`mapLegacyState`, `mapToLegacyState`) and enum definitions exported from `@debugmcp/shared`. Verifies backward compatibility between the legacy flat `SessionState` model and the new two-dimensional (`SessionLifecycleState` + `ExecutionState`) model.

## Test Structure

### `mapLegacyState` tests (L19–84)
Tests converting from legacy `SessionState` → `{ lifecycle, execution }` composite:
- `CREATED` → `{ lifecycle: CREATED }`, no execution (L20–26)
- `INITIALIZING` → `{ lifecycle: ACTIVE, execution: INITIALIZING }` (L28–34)
- `READY` → `{ lifecycle: ACTIVE, execution: INITIALIZING }` (L36–42) — **lossy mapping**: READY collapses to INITIALIZING
- `RUNNING` → `{ lifecycle: ACTIVE, execution: RUNNING }` (L44–50)
- `PAUSED` → `{ lifecycle: ACTIVE, execution: PAUSED }` (L52–58)
- `STOPPED` → `{ lifecycle: TERMINATED }`, no execution (L60–66)
- `ERROR` → `{ lifecycle: ACTIVE, execution: ERROR }` (L68–74)
- String value compatibility for external/JSON data (L77–83)

### `mapToLegacyState` tests (L86–151)
Tests converting from `(lifecycle, execution?)` → legacy `SessionState`:
- `CREATED` lifecycle → `CREATED` (lifecycle takes precedence over execution, L87–95)
- `TERMINATED` lifecycle → `STOPPED` (lifecycle takes precedence, L97–105)
- `ACTIVE` + `INITIALIZING` → `INITIALIZING` (L108–111)
- `ACTIVE` + `RUNNING` → `RUNNING` (L113–116)
- `ACTIVE` + `PAUSED` → `PAUSED` (L118–121)
- `ACTIVE` + `TERMINATED` → `STOPPED` (program ended but session still active, L123–126)
- `ACTIVE` + `ERROR` → `ERROR` (L128–131)
- `ACTIVE` + `undefined` → `READY` (default fallback, L133–141)
- String value compatibility (L145–150)

### Round-trip consistency tests (L153–202)
Verifies legacy → new → legacy round-trips. Notable asymmetry documented:
- `READY` → maps through new model → comes back as `INITIALIZING` (not `READY`), L168–173. This is an intentional, documented lossy mapping.

### Enum shape tests (L204–269)
Verifies exact enum values and counts:
- `DebugLanguage`: 8 values including `'python'`, `'mock'`, `'ruby'`, `'javascript'`, `'rust'`, `'go'`, `'java'`, `'dotnet'` (L205–224)
- `SessionLifecycleState`: 3 values — `'created'`, `'active'`, `'terminated'` (L226–237)
- `ExecutionState`: 5 values — `'initializing'`, `'running'`, `'paused'`, `'terminated'`, `'error'` (L239–252)
- `SessionState` (legacy): 7 values — `'created'`, `'initializing'`, `'ready'`, `'running'`, `'paused'`, `'stopped'`, `'error'` (L254–269)

### Edge case tests (L272–292)
- All lifecycle × execution combinations call `mapToLegacyState` without throwing (L273–283)
- All legacy states call `mapLegacyState` without throwing (L285–291)

### Type export verification (L294–316)
Constructs a full `DebugSession` object literal to validate TypeScript compilation succeeds with all expected fields: `id`, `language`, `name`, `state`, `sessionLifecycle`, `executionState`, `currentFile`, `currentLine`, `createdAt`, `updatedAt`, `breakpoints` (Map). (L300–312)

## Key Relationships
- All tested symbols (`mapLegacyState`, `mapToLegacyState`, `DebugLanguage`, `SessionLifecycleState`, `ExecutionState`, `SessionState`) are imported from `@debugmcp/shared` (L9–16)
- `DebugSession` interface is verified via inline `import('@debugmcp/shared').DebugSession` type (L300)

## Critical Invariants
- `READY` legacy state is a **lossy input**: after round-trip, it becomes `INITIALIZING` — this is intentional and documented in-test (L172)
- `ACTIVE + TERMINATED` execution maps to `STOPPED` legacy (not to `TERMINATED` lifecycle path), preserving semantic distinction between program-ended-in-active-session vs. session-terminated
- `CREATED` and `TERMINATED` lifecycle states ignore execution state entirely (lifecycle takes precedence)
