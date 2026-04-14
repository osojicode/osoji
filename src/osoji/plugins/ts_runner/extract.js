#!/usr/bin/env node
/**
 * ts-morph extraction runner for osoji TypeScript plugin.
 *
 * Usage:
 *   echo '["src/foo.ts","src/bar.ts"]' | node extract.js <tsconfig_path> [tsconfig_path...]
 *   echo '{"files":["src/foo.ts"]}' | node extract.js <tsconfig_path>
 *
 * Reads either a JSON array (backward compat) or a JSON object with "files"
 * from stdin.  Outputs a JSON object mapping each file path
 * to its extracted facts:
 *   { "src/foo.ts": { imports, exports, calls, member_writes } }
 */

const path = require("path");
const { createRequire } = require("module");

// Try to resolve ts-morph from this script's own node_modules first (installed
// by osoji), then fall back to the target project's node_modules.
let Project, SyntaxKind;
const scriptRequire = createRequire(path.join(__dirname, "package.json"));
try {
  ({ Project, SyntaxKind } = scriptRequire("ts-morph"));
} catch (_) {
  const cwdRequire = createRequire(path.join(process.cwd(), "package.json"));
  ({ Project, SyntaxKind } = cwdRequire("ts-morph"));
}

// ---------------------------------------------------------------------------
// Framework decorator detection
// ---------------------------------------------------------------------------

const FRAMEWORK_DECORATORS = new Set([
  "Controller", "Injectable", "Get", "Post", "Put", "Delete", "Patch",
  "Module", "Component", "Directive", "Pipe", "Entity", "Column",
  "Guard", "Interceptor", "Resolver", "EventPattern", "MessagePattern",
  "Cron", "Interval", "Timeout",
]);

const FRAMEWORK_SUFFIXES = [
  ".Get", ".Post", ".Put", ".Delete", ".Patch", ".Route",
  ".Handler", ".Listener", ".Subscribe", ".Command",
];

function hasFrameworkDecorator(decoratorNames) {
  for (const name of decoratorNames) {
    if (FRAMEWORK_DECORATORS.has(name)) return true;
    for (const suffix of FRAMEWORK_SUFFIXES) {
      if (name.endsWith(suffix)) return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Parameter extraction
// ---------------------------------------------------------------------------

function extractParameters(fn) {
  try {
    return fn.getParameters().map((p) => {
      let typeText;
      try {
        typeText = p.getType().getText();
      } catch (_) {
        typeText = "unknown";
      }
      return {
        name: p.getName(),
        optional: p.isOptional(),
        type: typeText.length > 200 ? typeText.substring(0, 200) : typeText,
      };
    });
  } catch (_) {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Scope-qualified from_symbol helper
// ---------------------------------------------------------------------------

function resolveFromSymbol(node) {
  let fromSymbol = "<module>";
  let parent = node.getParent();
  while (parent) {
    const kind = parent.getKind();
    if (kind === SyntaxKind.MethodDeclaration) {
      const methodName = parent.getName?.();
      const classParent = parent.getParent();
      if (
        classParent?.getKind() === SyntaxKind.ClassDeclaration
      ) {
        const className = classParent.getName?.();
        if (className && methodName) {
          fromSymbol = `${className}.${methodName}`;
          break;
        }
      }
      if (methodName) {
        fromSymbol = methodName;
        break;
      }
    }
    if (
      kind === SyntaxKind.FunctionDeclaration ||
      kind === SyntaxKind.ArrowFunction ||
      kind === SyntaxKind.FunctionExpression
    ) {
      const name = parent.getName?.();
      if (name) {
        fromSymbol = name;
        break;
      }
    }
    parent = parent.getParent();
  }
  return fromSymbol;
}

// ---------------------------------------------------------------------------
// CLI entry
// ---------------------------------------------------------------------------

const tsconfigPaths = process.argv.slice(2);
if (tsconfigPaths.length === 0) {
  process.stderr.write(
    "Usage: node extract.js <tsconfig_path> [tsconfig_path...]\n"
  );
  process.exit(1);
}

// Read file list from stdin
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  let filePaths;
  try {
    const parsed = JSON.parse(input);
    if (Array.isArray(parsed)) {
      // Backward compat: plain array of file paths
      filePaths = parsed;
    } else if (parsed && typeof parsed === "object" && Array.isArray(parsed.files)) {
      filePaths = parsed.files;
    } else {
      process.stderr.write("Invalid stdin: expected JSON array or {files, workspacePackages}\n");
      process.exit(1);
    }
  } catch (e) {
    process.stderr.write(`Invalid JSON on stdin: ${e.message}\n`);
    process.exit(1);
  }

  // Use first tsconfig for compiler options only — skip its file list so that
  // monorepo roots with "files": [] don't start the project empty.
  const project = new Project({
    tsConfigFilePath: tsconfigPaths[0],
    skipAddingFilesFromTsConfig: true,
  });

  // Load source files from ALL tsconfigs (including the first one)
  for (const tc of tsconfigPaths) {
    try {
      project.addSourceFilesFromTsConfig(tc);
    } catch (e) {
      process.stderr.write(
        `Warning: could not load ${tc}: ${e.message}\n`
      );
    }
  }

  // Add remaining files not covered by any tsconfig
  let addSkipped = 0;
  for (const relPath of filePaths) {
    if (!project.getSourceFile(relPath)) {
      try {
        project.addSourceFileAtPath(relPath);
      } catch (_) {
        addSkipped++;
      }
    }
  }
  if (addSkipped > 0) {
    process.stderr.write(
      `Note: ${addSkipped} file(s) could not be loaded by ts-morph\n`
    );
  }

  // =========================================================================
  // Pass 1: Per-file extraction
  // =========================================================================
  const result = {};
  let extractSkipped = 0;

  for (const relPath of filePaths) {
    const sourceFile = project.getSourceFile(relPath);
    if (!sourceFile) { extractSkipped++; continue; }

    const imports = [];
    const exports = [];
    const calls = [];
    const memberWrites = [];

    // --- Imports ---
    for (const decl of sourceFile.getImportDeclarations()) {
      const moduleSpec = decl.getModuleSpecifierValue();
      const names = [];
      const nameMap = {};
      const defaultImport = decl.getDefaultImport();
      if (defaultImport) names.push(defaultImport.getText());
      for (const named of decl.getNamedImports()) {
        const alias = named.getAliasNode()?.getText();
        const original = named.getName();
        const local = alias || original;
        names.push(local);
        if (alias) {
          nameMap[local] = original;
        }
      }
      const nsImport = decl.getNamespaceImport();
      if (nsImport) names.push(nsImport.getText());
      const imp = {
        source: moduleSpec,
        names,
        line: decl.getStartLineNumber(),
        is_reexport: false,
      };
      if (Object.keys(nameMap).length > 0) {
        imp.name_map = nameMap;
      }
      // Import resolution
      try {
        const resolvedFile = decl.getModuleSpecifierSourceFile();
        if (resolvedFile) {
          const resolvedPath = path
            .relative(process.cwd(), resolvedFile.getFilePath())
            .replace(/\\/g, "/");
          imp.resolved_path = resolvedPath;
        }
      } catch (_) {
        /* resolution failed — skip */
      }
      imports.push(imp);
    }

    // --- Exports ---

    // Functions (top-level)
    for (const fn of sourceFile.getFunctions()) {
      if (fn.isExported()) {
        const decorators = (fn.getDecorators?.() || []).map((d) => d.getName());
        const params = extractParameters(fn);
        const exp = {
          name: fn.getName() || "<anonymous>",
          kind: "function",
          line: fn.getStartLineNumber(),
          decorators,
          exclude_from_dead_analysis: hasFrameworkDecorator(decorators),
        };
        if (params.length > 0) {
          exp.parameters = params;
        }
        exports.push(exp);
      }
    }

    // Classes + methods
    for (const cls of sourceFile.getClasses()) {
      if (!cls.isExported()) continue;

      const className = cls.getName() || "<anonymous>";
      const classDecorators = cls.getDecorators().map((d) => d.getName());
      const classExclude = hasFrameworkDecorator(classDecorators);

      // Collect extends and implements
      const baseClass = cls.getBaseClass();
      const extendsName = baseClass ? baseClass.getName() : null;
      const implementsList = cls.getImplements().map((i) => i.getText());

      // Class-level export
      const classExport = {
        name: className,
        kind: "class",
        line: cls.getStartLineNumber(),
        decorators: classDecorators,
        exclude_from_dead_analysis: classExclude,
      };
      if (extendsName) {
        classExport.bases = [extendsName];
      }
      if (implementsList.length > 0) {
        classExport.implements = implementsList;
      }
      exports.push(classExport);

      // Method-level exports
      for (const method of cls.getMethods()) {
        if (
          method.hasModifier(SyntaxKind.PrivateKeyword) ||
          method.hasModifier(SyntaxKind.ProtectedKeyword)
        ) {
          continue;
        }

        const methodName = method.getName();
        const methodDecorators = method.getDecorators().map((d) => d.getName());
        const methodExclude =
          classExclude || hasFrameworkDecorator(methodDecorators);

        const params = extractParameters(method);

        const methodExport = {
          name: `${className}.${methodName}`,
          kind: "function",
          line: method.getStartLineNumber(),
          decorators: methodDecorators,
          exclude_from_dead_analysis: methodExclude,
        };
        if (params.length > 0) {
          methodExport.parameters = params;
        }
        exports.push(methodExport);
      }
    }

    // Variables
    for (const varStmt of sourceFile.getVariableStatements()) {
      if (varStmt.isExported()) {
        for (const decl of varStmt.getDeclarations()) {
          exports.push({
            name: decl.getName(),
            kind: "variable",
            line: decl.getStartLineNumber(),
            decorators: [],
            exclude_from_dead_analysis: false,
          });
        }
      }
    }

    // Interfaces
    for (const iface of sourceFile.getInterfaces()) {
      if (iface.isExported()) {
        exports.push({
          name: iface.getName(),
          kind: "type",
          line: iface.getStartLineNumber(),
          decorators: [],
          exclude_from_dead_analysis: false,
        });
      }
    }

    // Type aliases
    for (const typeAlias of sourceFile.getTypeAliases()) {
      if (typeAlias.isExported()) {
        exports.push({
          name: typeAlias.getName(),
          kind: "type",
          line: typeAlias.getStartLineNumber(),
          decorators: [],
          exclude_from_dead_analysis: false,
        });
      }
    }

    // Enums
    for (const enumDecl of sourceFile.getEnums()) {
      if (enumDecl.isExported()) {
        exports.push({
          name: enumDecl.getName(),
          kind: "constant",
          line: enumDecl.getStartLineNumber(),
          decorators: [],
          exclude_from_dead_analysis: false,
        });
      }
    }

    // --- Re-exports (named and star) ---
    for (const exportDecl of sourceFile.getExportDeclarations()) {
      const moduleSpec = exportDecl.getModuleSpecifierValue();
      if (moduleSpec) {
        const namedExports = exportDecl.getNamedExports();

        // Resolve the target module
        let resolvedPath = undefined;
        try {
          const resolvedFile = exportDecl.getModuleSpecifierSourceFile();
          if (resolvedFile) {
            resolvedPath = path
              .relative(process.cwd(), resolvedFile.getFilePath())
              .replace(/\\/g, "/");
          }
        } catch (_) {
          /* skip */
        }

        if (namedExports.length > 0) {
          // Named re-exports: export { x } from "./module"
          for (const named of namedExports) {
            const reexportImport = {
              source: moduleSpec,
              names: [named.getAliasNode()?.getText() || named.getName()],
              line: exportDecl.getStartLineNumber(),
              is_reexport: true,
            };
            if (resolvedPath !== undefined) {
              reexportImport.resolved_path = resolvedPath;
            }
            imports.push(reexportImport);
          }
        } else {
          // Star re-export: export * from "./module"
          const reexportImport = {
            source: moduleSpec,
            names: ["*"],
            line: exportDecl.getStartLineNumber(),
            is_reexport: true,
          };
          if (resolvedPath !== undefined) {
            reexportImport.resolved_path = resolvedPath;
          }
          imports.push(reexportImport);
        }
      }
    }

    // --- Calls (including new expressions) ---
    sourceFile.forEachDescendant((node) => {
      if (node.getKind() === SyntaxKind.CallExpression) {
        const expr = node.getExpression();
        const callee = expr.getText();
        const fromSymbol = resolveFromSymbol(node);
        calls.push({
          from_symbol: fromSymbol,
          to: callee.length > 100 ? callee.substring(0, 100) : callee,
          line: node.getStartLineNumber(),
        });
      }

      // Constructor calls: new ClassName()
      if (node.getKind() === SyntaxKind.NewExpression) {
        const expr = node.getExpression();
        const callee = expr.getText();
        const fromSymbol = resolveFromSymbol(node);
        calls.push({
          from_symbol: fromSymbol,
          to: callee.length > 100 ? callee.substring(0, 100) : callee,
          line: node.getStartLineNumber(),
        });
      }

      // --- Member writes ---
      if (
        node.getKind() === SyntaxKind.BinaryExpression &&
        node.getOperatorToken().getKind() === SyntaxKind.EqualsToken
      ) {
        const left = node.getLeft();
        if (left.getKind() === SyntaxKind.PropertyAccessExpression) {
          const propAccess = left;
          memberWrites.push({
            container: propAccess.getExpression().getText(),
            member: propAccess.getName(),
            line: node.getStartLineNumber(),
          });
        }
      }
    });

    result[relPath] = {
      imports,
      exports,
      calls,
      member_writes: memberWrites,
    };
  }

  // =========================================================================
  // Pass 2: Cross-file call resolution
  // =========================================================================

  // Build import maps: file -> { localName: { resolvedPath, originalName } }
  const importMaps = {};
  for (const [relPath, data] of Object.entries(result)) {
    const imap = {};
    for (const imp of data.imports) {
      if (!imp.resolved_path) continue;
      const aliasMap = imp.name_map || {};
      for (const name of imp.names) {
        if (name === "*") continue;
        const original = aliasMap[name] || name;
        imap[name] = { resolvedPath: imp.resolved_path, originalName: original };
      }
    }
    importMaps[relPath] = imap;
  }

  // Resolve a call to its cross-file key ("defFile::symbolName").
  function crossCallKey(relPath, callee, imap) {
    const root = callee.split(".")[0];
    if (imap[root]) {
      const { resolvedPath, originalName } = imap[root];
      const resolvedName = callee.includes(".")
        ? originalName + callee.substring(root.length)
        : originalName;
      return `${resolvedPath}::${resolvedName}`;
    }
    return `${relPath}::${callee}`;
  }

  // Count cross-file call sites
  const crossCallCounts = {}; // "defFile::symbolName" -> count
  for (const [relPath, data] of Object.entries(result)) {
    const imap = importMaps[relPath] || {};
    for (const call of data.calls) {
      const key = crossCallKey(relPath, call.to, imap);
      crossCallCounts[key] = (crossCallCounts[key] || 0) + 1;
    }
  }

  // Write back call_sites on each call record
  for (const [relPath, data] of Object.entries(result)) {
    const imap = importMaps[relPath] || {};
    for (const call of data.calls) {
      const key = crossCallKey(relPath, call.to, imap);
      call.call_sites = crossCallCounts[key] || 0;
    }
  }

  const extracted = Object.keys(result).length;
  process.stderr.write(
    `ts-morph: extracted ${extracted}/${filePaths.length} files` +
    (extractSkipped > 0 ? ` (${extractSkipped} not loadable)` : "") +
    "\n"
  );

  process.stdout.write(JSON.stringify(result));
});
