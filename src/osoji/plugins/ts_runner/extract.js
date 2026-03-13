#!/usr/bin/env node
/**
 * ts-morph extraction runner for osoji TypeScript plugin.
 *
 * Usage: echo '["src/foo.ts","src/bar.ts"]' | node extract.js <tsconfig_path>
 *
 * Reads a JSON array of relative file paths from stdin.
 * Outputs a JSON object mapping each file path to its extracted facts:
 *   { "src/foo.ts": { imports: [...], exports: [...], calls: [...], member_writes: [...] } }
 */

const { Project, SyntaxKind } = require("ts-morph");

const tsconfigPath = process.argv[2];
if (!tsconfigPath) {
  process.stderr.write("Usage: node extract.js <tsconfig_path>\n");
  process.exit(1);
}

// Read file list from stdin
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  let filePaths;
  try {
    filePaths = JSON.parse(input);
  } catch (e) {
    process.stderr.write(`Invalid JSON on stdin: ${e.message}\n`);
    process.exit(1);
  }

  const project = new Project({ tsConfigFilePath: tsconfigPath });
  const result = {};

  for (const relPath of filePaths) {
    const sourceFile = project.getSourceFile(relPath);
    if (!sourceFile) continue;

    const imports = [];
    const exports = [];
    const calls = [];
    const memberWrites = [];

    // --- Imports ---
    for (const decl of sourceFile.getImportDeclarations()) {
      const moduleSpec = decl.getModuleSpecifierValue();
      const names = [];
      const defaultImport = decl.getDefaultImport();
      if (defaultImport) names.push(defaultImport.getText());
      for (const named of decl.getNamedImports()) {
        names.push(named.getAliasNode()?.getText() || named.getName());
      }
      const nsImport = decl.getNamespaceImport();
      if (nsImport) names.push(nsImport.getText());
      imports.push({
        source: moduleSpec,
        names,
        line: decl.getStartLineNumber(),
        is_reexport: false,
      });
    }

    // --- Exports ---
    for (const fn of sourceFile.getFunctions()) {
      if (fn.isExported()) {
        exports.push({
          name: fn.getName() || "<anonymous>",
          kind: "function",
          line: fn.getStartLineNumber(),
          decorators: [],
          exclude_from_dead_analysis: false,
        });
      }
    }
    for (const cls of sourceFile.getClasses()) {
      if (cls.isExported()) {
        exports.push({
          name: cls.getName() || "<anonymous>",
          kind: "class",
          line: cls.getStartLineNumber(),
          decorators: cls
            .getDecorators()
            .map((d) => d.getName()),
          exclude_from_dead_analysis: false,
        });
      }
    }
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

    // Re-export detection
    for (const exportDecl of sourceFile.getExportDeclarations()) {
      const moduleSpec = exportDecl.getModuleSpecifierValue();
      if (moduleSpec) {
        for (const named of exportDecl.getNamedExports()) {
          imports.push({
            source: moduleSpec,
            names: [named.getAliasNode()?.getText() || named.getName()],
            line: exportDecl.getStartLineNumber(),
            is_reexport: true,
          });
        }
      }
    }

    // --- Calls ---
    sourceFile.forEachDescendant((node) => {
      if (node.getKind() === SyntaxKind.CallExpression) {
        const expr = node.getExpression();
        const callee = expr.getText();
        // Find enclosing function/method
        let fromSymbol = "<module>";
        let parent = node.getParent();
        while (parent) {
          if (
            parent.getKind() === SyntaxKind.FunctionDeclaration ||
            parent.getKind() === SyntaxKind.MethodDeclaration ||
            parent.getKind() === SyntaxKind.ArrowFunction ||
            parent.getKind() === SyntaxKind.FunctionExpression
          ) {
            const name = parent.getName?.();
            if (name) {
              fromSymbol = name;
              break;
            }
          }
          parent = parent.getParent();
        }
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

    // Per-file reference counts for calls
    const callSiteCounts = {};
    for (const call of calls) {
      const key = call.to;
      callSiteCounts[key] = (callSiteCounts[key] || 0) + 1;
    }
    for (const call of calls) {
      call.call_sites = callSiteCounts[call.to] || 0;
    }

    result[relPath] = {
      imports,
      exports,
      calls,
      member_writes: memberWrites,
    };
  }

  process.stdout.write(JSON.stringify(result));
});
