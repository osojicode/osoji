# src\osoji\plugins\ts_runner\extract.js
@source-hash: eee3711a37abdeaa
@impl-hash: 0b90021c7fbb6c9e
@generated: 2026-07-22T10:55:16Z

## Purpose
CLI script (Node.js entry point) that uses `ts-morph` to extract TypeScript AST facts from source files. Reads a file list from stdin, processes each file through a two-pass extraction pipeline, and writes a JSON result map to stdout. Consumed by the osoji TypeScript plugin.

## Architecture

### Two-Pass Pipeline
1. **Pass 1 (L196–478):** Per-file extraction — imports, exports, calls (including `new` expressions), and member writes.
2. **Pass 2 (L484–530):** Cross-file call resolution — builds import maps, resolves callees to `"defFile::symbolName"` keys, counts call sites, and writes `call_sites` back onto each call record.

### ts-morph Resolution (L20–27)
Attempts to load `ts-morph` from the script's own `node_modules` (osoji-installed), falling back to the target project's `node_modules`. Uses `createRequire` to scope resolution correctly.

### Input Format (L133–153)
Reads JSON from stdin. Accepts either:
- A plain JSON array `["src/foo.ts", ...]` (backward compat, L141–143)
- A JSON object `{"files": ["src/foo.ts", ...]}` (L144–145)

### Project Setup (L157–188)
- Creates a `ts-morph` `Project` with the first tsconfig for compiler options only (`skipAddingFilesFromTsConfig: true`, L159).
- Loads source files from ALL tsconfigs (L163–171), preventing monorepo roots with `"files": []` from producing an empty project.
- Adds any remaining requested files not covered by any tsconfig (L175–188).

## Key Functions

### `hasFrameworkDecorator(decoratorNames)` (L45–53)
Returns `true` if any decorator name matches the `FRAMEWORK_DECORATORS` set or ends with any `FRAMEWORK_SUFFIXES` entry. Used to set `exclude_from_dead_analysis` on exports.

### `extractParameters(fn)` (L59–77)
Extracts parameter metadata from a ts-morph function/method node. Returns `[{name, optional, type}]`. Type text is capped at 200 chars. Returns `[]` on any error.

### `resolveFromSymbol(node)` (L83–119)
Walks ancestor nodes to determine the enclosing function/method scope. Returns `"ClassName.methodName"` for class methods, bare function name for standalone functions, or `"<module>"` for top-level code.

### `crossCallKey(relPath, callee, imap)` (L501–511)
Resolves a callee string to a cross-file key `"defFile::symbolName"`. Splits on `.` to get the root import name, then maps through the import alias map. Falls back to `"currentFile::callee"` for unresolved names.

## Output Format
Writes to stdout: `{ "src/foo.ts": { imports, exports, calls, member_writes } }`

Each **import** entry: `{ source, names, line, is_reexport, name_map?, resolved_path? }`  
Each **export** entry: `{ name, kind, line, decorators, exclude_from_dead_analysis, parameters?, bases?, implements? }`  
Each **call** entry: `{ from_symbol, to, line, call_sites }`  
Each **member_write** entry: `{ container, member, line }`

Re-exports (L382–428) are recorded in `imports` with `is_reexport: true`, using `names: ["*"]` for star re-exports.

## Constants

### `FRAMEWORK_DECORATORS` (L33–38)
Set of NestJS/TypeORM/Angular/etc. decorator names that mark a symbol as framework-entrypoint (excluded from dead-code analysis).

### `FRAMEWORK_SUFFIXES` (L40–43)
Decorator name suffixes (e.g., `.Get`, `.Post`) for decorator factory patterns not captured by the exact-name set.

## CLI Usage
```
echo '["src/foo.ts"]' | node extract.js tsconfig.json [tsconfig2.json ...]
```
Exits with code 1 if no tsconfig paths provided or stdin is invalid JSON.

## Error Handling
- File load failures logged to stderr; skipped silently with counter (L184–188).
- Unloadable files during extraction are skipped with counter (L198, L533–537).
- Type text resolution failures default to `"unknown"` (L65–66).
- Import/export path resolution failures are silently skipped (L241–243, L396–398).
