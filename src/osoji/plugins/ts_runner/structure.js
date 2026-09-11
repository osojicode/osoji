#!/usr/bin/env node
/**
 * Structure extraction for osoji's code-claim registries (Tier A on code).
 *
 * Usage:
 *   echo '{"files":["src/foo.ts"]}' | node structure.js
 *
 * ts-morph is used as a PARSER only: no tsconfig, no dependency resolution, no
 * type checker. That is deliberate -- the registries built from this output
 * must be decidable from the tree alone, in a bare worktree with nothing
 * installed. Everything type-level (what a member access resolves to, whether
 * a class satisfies an interface) is answered downstream by registries in
 * osoji, not by the compiler here.
 *
 * Output: one JSON object mapping each requested file to its structure facts,
 * in a language-neutral shape documented in osoji/plugins/base.py
 * (StructureFacts). Line numbers are 1-based.
 */

const path = require("path");
const { createRequire } = require("module");

let Project, SyntaxKind, Node;
const scriptRequire = createRequire(path.join(__dirname, "package.json"));
try {
  ({ Project, SyntaxKind, Node } = scriptRequire("ts-morph"));
} catch (_) {
  const cwdRequire = createRequire(path.join(process.cwd(), "package.json"));
  ({ Project, SyntaxKind, Node } = cwdRequire("ts-morph"));
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** `Foo<T>` -> `Foo`, `ns.Foo` kept as written. */
function bareTypeName(text) {
  const lt = text.indexOf("<");
  return (lt >= 0 ? text.substring(0, lt) : text).trim();
}

function typeNodeInfo(typeNode) {
  // Returns { type: referenceName | null, members: [names] | null, open: bool }
  if (!typeNode) return { type: null, members: null, open: true };
  if (Node.isTypeReference(typeNode)) {
    return { type: bareTypeName(typeNode.getTypeName().getText()), members: null, open: false };
  }
  if (Node.isTypeLiteral(typeNode)) {
    const members = [];
    let open = false;
    for (const m of typeNode.getMembers()) {
      if (Node.isPropertySignature(m) || Node.isMethodSignature(m)) members.push(m.getName());
      else if (Node.isIndexSignatureDeclaration(m)) open = true;
    }
    return { type: null, members, open };
  }
  if (Node.isIntersectionTypeNode(typeNode)) {
    // Members of literal parts plus the referenced parts, all to be merged
    // downstream; any non-literal, non-reference part makes it open.
    const refs = [];
    const members = [];
    let open = false;
    for (const part of typeNode.getTypeNodes()) {
      const info = typeNodeInfo(part);
      if (info.type) refs.push(info.type);
      else if (info.members) members.push(...info.members);
      else open = true;
      if (info.open) open = true;
    }
    return { type: null, members, open, intersection: refs };
  }
  // unions, mapped types, keyof, typeof, arrays, primitives: not a closed
  // member set the registry can reason about
  return { type: null, members: null, open: true, text: typeNode.getText().slice(0, 80) };
}

function paramInfo(p) {
  const t = typeNodeInfo(p.getTypeNode());
  const out = {
    name: p.getName(),
    optional: p.isOptional() || p.hasInitializer(),
    rest: p.isRestParameter(),
    type: t.type,
    members: t.members,
    open: t.open,
  };
  if (t.intersection) out.intersection = t.intersection;
  return out;
}

function paramList(fnLike) {
  try {
    return fnLike.getParameters().map(paramInfo);
  } catch (_) {
    return [];
  }
}

function requiredCount(params) {
  let n = 0;
  for (const p of params) {
    if (p.optional || p.rest) break;
    n++;
  }
  return n;
}

function objectLiteralMembers(obj) {
  const members = [];
  let open = false;
  for (const prop of obj.getProperties()) {
    if (Node.isSpreadAssignment(prop)) { open = true; continue; }
    let name = null;
    try {
      name = prop.getName ? prop.getName() : null;
    } catch (_) { name = null; }
    if (name == null) { open = true; continue; }
    // computed keys like [SOME_CONST]: keep as written but mark open
    if (name.startsWith("[")) { open = true; continue; }
    members.push({ name: name.replace(/^['"]|['"]$/g, ""), kind: Node.isMethodDeclaration(prop) ? "method" : "property", line: prop.getStartLineNumber() });
  }
  return { members, open };
}

/** A member's declaration text with comments and whitespace normalised, for copy comparison. */
function signatureText(node) {
  try {
    return node.getText().replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "").replace(/\s+/g, " ").replace(/;\s*$/, "").trim();
  } catch (_) {
    return null;
  }
}

function interfaceMembers(iface) {
  const members = [];
  let open = false;
  for (const m of iface.getMembers()) {
    if (Node.isPropertySignature(m)) {
      members.push({ name: m.getName(), kind: "property", optional: m.hasQuestionToken(), line: m.getStartLineNumber(), signature: signatureText(m) });
    } else if (Node.isMethodSignature(m)) {
      const params = paramList(m);
      members.push({ name: m.getName(), kind: "method", optional: m.hasQuestionToken(), params: params.length, required_params: requiredCount(params), param_list: params, line: m.getStartLineNumber(), signature: signatureText(m) });
    } else if (Node.isIndexSignatureDeclaration(m)) {
      open = true;
    }
    // call/construct signatures carry no name; they do not affect member sets
  }
  return { members, open };
}

function classMembers(cls) {
  const members = [];
  const add = (name, kind, extra) => members.push({ name, kind, ...extra });
  for (const ctor of cls.getConstructors()) {
    for (const p of ctor.getParameters()) {
      // constructor(public readonly sessionId: string) declares a property
      if (p.getScope && (p.hasScopeKeyword?.() || p.isReadonly?.())) {
        add(p.getName(), "property", { static: false, line: p.getStartLineNumber() });
      }
    }
  }
  for (const prop of cls.getProperties()) {
    add(prop.getName(), "property", { static: prop.isStatic(), optional: prop.hasQuestionToken?.() || false, line: prop.getStartLineNumber() });
  }
  for (const acc of [...cls.getGetAccessors(), ...cls.getSetAccessors()]) {
    add(acc.getName(), "property", { static: acc.isStatic(), line: acc.getStartLineNumber() });
  }
  for (const method of cls.getMethods()) {
    const params = paramList(method);
    add(method.getName(), "method", {
      static: method.isStatic(),
      params: params.length,
      required_params: requiredCount(params),
      param_list: params,
      line: method.getStartLineNumber(),
      private: method.hasModifier(SyntaxKind.PrivateKeyword) || method.hasModifier(SyntaxKind.ProtectedKeyword),
    });
  }
  return members;
}

// ---------------------------------------------------------------------------
// per-file extraction
// ---------------------------------------------------------------------------

/**
 * True when an enclosing function, method, block or catch clause declares a
 * parameter or variable named `name`: the identifier then binds there, not to
 * the module-level declaration the registry knows. Purely syntactic.
 */
function isShadowed(node, name) {
  let parent = node.getParent();
  while (parent && !Node.isSourceFile(parent)) {
    try {
      if (parent.getParameters) {
        for (const p of parent.getParameters()) {
          if (p.getName?.() === name) return true;
          // destructured parameters: ({ config }) => ...
          const nameNode = p.getNameNode?.();
          if (nameNode && !Node.isIdentifier(nameNode) && nameNode.getText().split(/[^A-Za-z0-9_$]+/).includes(name)) return true;
        }
      }
      if (Node.isBlock(parent) || Node.isSourceFile(parent) || Node.isCaseClause?.(parent) || Node.isModuleBlock?.(parent)) {
        for (const stmt of parent.getStatements?.() || []) {
          if (Node.isVariableStatement(stmt)) {
            for (const d of stmt.getDeclarations()) {
              if (d.getName() === name) return true;
              const nameNode = d.getNameNode?.();
              if (nameNode && !Node.isIdentifier(nameNode) && nameNode.getText().split(/[^A-Za-z0-9_$]+/).includes(name)) return true;
            }
          } else if ((Node.isFunctionDeclaration(stmt) || Node.isClassDeclaration(stmt) || Node.isEnumDeclaration(stmt)) && stmt.getName?.() === name) {
            return true;
          }
        }
      }
      if (Node.isCatchClause(parent)) {
        const v = parent.getVariableDeclaration?.();
        if (v && v.getName() === name) return true;
      }
      if (Node.isForOfStatement?.(parent) || Node.isForInStatement?.(parent) || Node.isForStatement?.(parent)) {
        const init = parent.getInitializer?.();
        if (init && Node.isVariableDeclarationList(init)) {
          for (const d of init.getDeclarations()) if (d.getName() === name) return true;
        }
      }
    } catch (_) { /* keep walking */ }
    parent = parent.getParent();
  }
  return false;
}

/** The nearest enclosing class name, or null. */
function enclosingClassName(node) {
  let parent = node.getParent();
  while (parent) {
    if (Node.isClassDeclaration(parent) || Node.isClassExpression(parent)) return parent.getName?.() || null;
    parent = parent.getParent();
  }
  return null;
}

/** `let x: T`, `const x = new T(...)`, `x = new T(...)`, or a parameter `x: T` -- the receiver types a call can bind through. */
function collectLocals(sourceFile, locals) {
  sourceFile.forEachDescendant((node) => {
    if (Node.isVariableDeclaration(node) || Node.isParameterDeclaration(node) || Node.isPropertyDeclaration(node)) {
      const name = node.getName?.();
      if (!name || name.startsWith("{") || name.startsWith("[")) return;
      let type = null;
      const tn = node.getTypeNode?.();
      if (tn && Node.isTypeReference(tn)) type = bareTypeName(tn.getTypeName().getText());
      const init = node.getInitializer?.();
      if (!type && init && Node.isNewExpression(init)) type = bareTypeName(init.getExpression().getText());
      if (!type && init && (Node.isAsExpression(init) || Node.isSatisfiesExpression(init))) {
        const t = init.getTypeNode();
        if (t && Node.isTypeReference(t)) type = bareTypeName(t.getTypeName().getText());
      }
      if (type) locals.push({ name, type, line: node.getStartLineNumber(), kind: Node.isPropertyDeclaration(node) ? "property" : "local" });
    }
    if (Node.isBinaryExpression(node) && node.getOperatorToken().getKind() === SyntaxKind.EqualsToken) {
      const left = node.getLeft();
      const right = node.getRight();
      if (Node.isIdentifier(left) && Node.isNewExpression(right)) {
        locals.push({ name: left.getText(), type: bareTypeName(right.getExpression().getText()), line: node.getStartLineNumber(), kind: "assignment" });
      }
    }
  });
}

function extractFile(sourceFile) {
  const imports = [];
  const declarations = [];
  const memberRefs = [];
  const calls = [];
  const localExports = [];
  const locals = [];
  collectLocals(sourceFile, locals);

  for (const decl of sourceFile.getImportDeclarations()) {
    const names = [];
    const nameMap = {};
    const def = decl.getDefaultImport();
    let defaultName = null;
    if (def) { defaultName = def.getText(); names.push(defaultName); }
    for (const named of decl.getNamedImports()) {
      const alias = named.getAliasNode()?.getText();
      const original = named.getName();
      const local = alias || original;
      names.push(local);
      if (alias) nameMap[local] = original;
    }
    const ns = decl.getNamespaceImport();
    imports.push({
      specifier: decl.getModuleSpecifierValue(),
      names,
      name_map: nameMap,
      default: defaultName,
      namespace: ns ? ns.getText() : null,
      line: decl.getStartLineNumber(),
      reexport: false,
      star: false,
      type_only: decl.isTypeOnly(),
    });
  }

  for (const exp of sourceFile.getExportDeclarations()) {
    const spec = exp.getModuleSpecifierValue();
    const named = exp.getNamedExports();
    if (spec) {
      if (named.length > 0) {
        for (const n of named) {
          const alias = n.getAliasNode()?.getText();
          imports.push({ specifier: spec, names: [alias || n.getName()], name_map: alias ? { [alias]: n.getName() } : {}, default: null, namespace: null, line: exp.getStartLineNumber(), reexport: true, star: false, type_only: exp.isTypeOnly() });
        }
      } else {
        imports.push({ specifier: spec, names: ["*"], name_map: {}, default: null, namespace: null, line: exp.getStartLineNumber(), reexport: true, star: true, type_only: exp.isTypeOnly() });
      }
    } else {
      for (const n of named) {
        localExports.push({ name: n.getName(), alias: n.getAliasNode()?.getText() || null });
      }
    }
  }

  for (const e of sourceFile.getEnums()) {
    declarations.push({
      name: e.getName(), kind: "enum", exported: e.isExported(), line: e.getStartLineNumber(),
      members: e.getMembers().map((m) => ({ name: m.getName(), kind: "member", line: m.getStartLineNumber() })), open: false,
    });
  }

  for (const iface of sourceFile.getInterfaces()) {
    const { members, open } = interfaceMembers(iface);
    declarations.push({
      name: iface.getName(), kind: "interface", exported: iface.isExported(), line: iface.getStartLineNumber(),
      extends: iface.getExtends().map((x) => bareTypeName(x.getText())), members, open,
    });
  }

  for (const alias of sourceFile.getTypeAliases()) {
    const t = typeNodeInfo(alias.getTypeNode());
    const d = {
      name: alias.getName(), kind: "type", exported: alias.isExported(), line: alias.getStartLineNumber(),
      members: t.members ? t.members.map((n) => ({ name: n, kind: "property" })) : null,
      open: t.open, extends: t.intersection || (t.type ? [t.type] : []),
    };
    declarations.push(d);
  }

  for (const cls of sourceFile.getClasses()) {
    const ext = cls.getExtends();
    declarations.push({
      name: cls.getName() || "<anonymous>", kind: "class", exported: cls.isExported(), line: cls.getStartLineNumber(),
      extends: ext ? [bareTypeName(ext.getExpression().getText())] : [],
      implements: cls.getImplements().map((i) => bareTypeName(i.getText())),
      members: classMembers(cls), open: false,
    });
  }

  for (const fn of sourceFile.getFunctions()) {
    const params = paramList(fn);
    declarations.push({
      name: fn.getName() || "<anonymous>", kind: "function", exported: fn.isExported(), line: fn.getStartLineNumber(),
      params, required_params: requiredCount(params),
    });
  }

  for (const stmt of sourceFile.getVariableStatements()) {
    const exported = stmt.isExported();
    for (const decl of stmt.getDeclarations()) {
      let init = decl.getInitializer();
      let annotation = decl.getTypeNode() ? bareTypeName(decl.getTypeNode().getText()) : null;
      // `= {...} satisfies T` / `= {...} as T` -- unwrap, remember T
      while (init && (Node.isSatisfiesExpression(init) || Node.isAsExpression(init) || Node.isParenthesizedExpression(init))) {
        if (!Node.isParenthesizedExpression(init) && !annotation) {
          annotation = bareTypeName(init.getTypeNode().getText());
        }
        init = init.getExpression();
      }
      if (init && Node.isObjectLiteralExpression(init)) {
        const { members, open } = objectLiteralMembers(init);
        declarations.push({ name: decl.getName(), kind: "object", exported, line: decl.getStartLineNumber(), annotation, members, open });
      } else if (init && (Node.isArrowFunction(init) || Node.isFunctionExpression(init))) {
        const params = paramList(init);
        declarations.push({ name: decl.getName(), kind: "function", exported, line: decl.getStartLineNumber(), params, required_params: requiredCount(params) });
      } else {
        declarations.push({ name: decl.getName(), kind: "variable", exported, line: decl.getStartLineNumber(), annotation });
      }
    }
  }

  sourceFile.forEachDescendant((node) => {
    if (Node.isPropertyAccessExpression(node)) {
      const obj = node.getExpression();
      if (Node.isIdentifier(obj)) {
        const parent = node.getParent();
        const isCall = Node.isCallExpression(parent) && parent.getExpression() === node;
        const optional = node.hasQuestionDotToken() || (isCall && parent.hasQuestionDotToken?.());
        memberRefs.push({ object: obj.getText(), member: node.getName(), line: node.getStartLineNumber(), optional: !!optional, call: !!isCall,
                          shadowed: isShadowed(node, obj.getText()) });
      }
    }
    if (Node.isCallExpression(node)) {
      const args = [];
      node.getArguments().forEach((arg, index) => {
        if (Node.isObjectLiteralExpression(arg)) {
          const { members, open } = objectLiteralMembers(arg);
          args.push({ index, keys: members.map((m) => m.name), spread: open });
        }
      });
      if (args.length > 0) {
        const expr = node.getExpression();
        let member = null;
        let receiver = null;
        if (Node.isPropertyAccessExpression(expr)) {
          member = expr.getName();
          const obj = expr.getExpression();
          if (Node.isIdentifier(obj)) receiver = obj.getText();
          else if (obj.getKind() === SyntaxKind.ThisKeyword) receiver = "this";
          else receiver = "<expression>";
        } else if (Node.isIdentifier(expr)) {
          member = expr.getText();
        }
        const calleeText = expr.getText();
        calls.push({ callee: calleeText.length > 100 ? calleeText.substring(0, 100) : calleeText, member, receiver,
                     enclosing_class: enclosingClassName(node), line: node.getStartLineNumber(), args });
      }
    }
  });

  return { imports, declarations, member_refs: memberRefs, calls, local_exports: localExports, locals };
}

// ---------------------------------------------------------------------------
// CLI entry
// ---------------------------------------------------------------------------

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  let files;
  try {
    const parsed = JSON.parse(input);
    files = Array.isArray(parsed) ? parsed : parsed.files;
    if (!Array.isArray(files)) throw new Error("expected {files: [...]}");
  } catch (e) {
    process.stderr.write(`Invalid stdin: ${e.message}\n`);
    process.exit(1);
  }
  const project = new Project({
    useInMemoryFileSystem: false,
    skipFileDependencyResolution: true,
    skipLoadingLibFiles: true,
    compilerOptions: { allowJs: true, noResolve: true, skipLibCheck: true },
  });
  const result = {};
  let skipped = 0;
  for (const rel of files) {
    let sf;
    try {
      sf = project.addSourceFileAtPath(rel);
    } catch (_) { skipped++; continue; }
    try {
      result[rel] = extractFile(sf);
    } catch (e) {
      skipped++;
      process.stderr.write(`structure: ${rel}: ${e.message}\n`);
    }
  }
  process.stderr.write(`structure: extracted ${Object.keys(result).length}/${files.length} files${skipped ? ` (${skipped} skipped)` : ""}\n`);
  process.stdout.write(JSON.stringify(result));
});
