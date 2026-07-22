"""Python language plugin — deterministic AST extraction using stdlib ``ast``."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import Any

from .base import ExtractedFacts, LanguagePlugin
from .python_resolution import annotate_call_sites, normalize_path

logger = logging.getLogger(__name__)

# Decorators that indicate framework/convention usage — these symbols should
# have ``exclude_from_dead_analysis: True`` on their exports.
_FRAMEWORK_DECORATOR_NAMES: frozenset[str] = frozenset({
    "property",
    "classmethod",
    "staticmethod",
    "abstractmethod",
    "pytest.fixture",
    "fixture",
    "app.route",
    "router.get",
    "router.post",
    "router.put",
    "router.delete",
    "router.patch",
    "signal.connect",
    "receiver",
    "task",
    "shared_task",
    "command",
    "group",
    "click.command",
    "click.group",
})

# Decorator name suffixes that indicate framework registration.
_FRAMEWORK_DECORATOR_SUFFIXES: tuple[str, ...] = (
    ".route",
    ".command",
    ".group",
    ".get",
    ".post",
    ".put",
    ".delete",
    ".patch",
    ".connect",
    ".handler",
    ".listener",
)


def _decorator_name(node: ast.expr) -> str:
    """Resolve a decorator node to a dotted string name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _decorator_name(node.value)
        if prefix:
            return f"{prefix}.{node.attr}"
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _resolve_base_name(node: ast.expr) -> str:
    """Resolve a class base to a dotted name, unwrapping subscripted generics.

    ``class UserRepo(CRUDBase[User])`` must yield ``CRUDBase`` — dropping the
    base would sever the inheritance edge dead-code liveness propagation needs.
    """
    if isinstance(node, ast.Subscript):
        return _resolve_base_name(node.value)
    return _decorator_name(node)


def _has_framework_decorator(decorators: list[ast.expr]) -> bool:
    """Return True if any decorator indicates framework/convention usage."""
    for dec in decorators:
        name = _decorator_name(dec)
        if name in _FRAMEWORK_DECORATOR_NAMES:
            return True
        if any(name.endswith(suffix) for suffix in _FRAMEWORK_DECORATOR_SUFFIXES):
            return True
    return False


def _decorator_names(decorators: list[ast.expr]) -> list[str]:
    """Return list of decorator name strings."""
    return [n for d in decorators if (n := _decorator_name(d))]


def _resolve_callee(node: ast.expr) -> str:
    """Resolve a Call node's function to a dotted name string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _resolve_callee(node.value)
        if prefix:
            return f"{prefix}.{node.attr}"
        return node.attr
    return ""


def _get_all_members(node: ast.Module) -> list[str] | None:
    """Extract __all__ from a module if it's a simple list/tuple of strings."""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    return _extract_string_list(stmt.value)
        if isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__" and stmt.value is not None:
                return _extract_string_list(stmt.value)
        if isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
                # __all__ += [...] — can't reliably resolve
                return None
    return None


def _extract_string_list(node: ast.expr) -> list[str] | None:
    """Extract a list/tuple of string constants, or None if not simple."""
    if isinstance(node, (ast.List, ast.Tuple)):
        result = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                result.append(elt.value)
            else:
                return None  # Non-constant element
        return result
    return None


def _current_scope(scope_stack: list[str]) -> str:
    """Return the current scope name from the stack, or '<module>'."""
    return scope_stack[-1] if scope_stack else "<module>"


def _collect_docstring_lines(body: list[ast.stmt]) -> set[int]:
    """Return line numbers of docstring nodes in a body."""
    lines: set[int] = set()
    if body and isinstance(body[0], ast.Expr):
        val = body[0].value
        if isinstance(val, ast.Constant) and isinstance(val.value, str):
            lines.add(val.lineno)
    return lines


def _annotate_parents(tree: ast.AST) -> None:
    """Add _parent attribute to every node in the tree."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # type: ignore[attr-defined]


class _FileExtractor(ast.NodeVisitor):
    """Extract imports, exports, calls, member_writes, and string_literals from a single file."""

    def __init__(
        self,
        *,
        relative_path: str,
        is_init: bool,
        all_members: list[str] | None,
    ):
        self.relative_path = relative_path
        self.is_init = is_init
        self.all_members = all_members
        self.all_set: set[str] | None = set(all_members) if all_members is not None else None

        self.imports: list[dict[str, Any]] = []
        self.exports: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.member_writes: list[dict[str, Any]] = []
        self.string_literals: list[dict[str, Any]] = []

        self._scope_stack: list[str] = []
        self._depth = 0  # nesting depth for top-level detection
        self._class_scope_depth = 0  # tracks whether we're inside a class body
        self._docstring_lines: set[int] = set()

    def _is_exported(self, name: str) -> bool:
        """Decide whether a name should be in exports."""
        if self.all_set is not None:
            return name in self.all_set
        # Exclude _private and dunders unless in __all__
        if name.startswith("_"):
            return False
        return True

    # --- Imports ---

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name
            is_reexport = (
                self.is_init
                and not local.startswith("_")
                and (self.all_set is None or local in self.all_set)
            )
            imp: dict = {
                "source": alias.name,
                "names": [local],
                "line": node.lineno,
                "is_reexport": is_reexport,
            }
            if alias.asname:
                imp["name_map"] = {local: alias.name}
            self.imports.append(imp)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        level = node.level or 0
        dots = "." * level
        module = node.module or ""
        source = f"{dots}{module}" if dots else module

        names = []
        name_map: dict[str, str] = {}
        for alias in (node.names or []):
            local = alias.asname or alias.name
            names.append(local)
            if alias.asname:
                name_map[local] = alias.name

        is_reexport = False
        if self.is_init:
            # In __init__.py, imported public names (or names in __all__) are re-exports
            public_names = [
                n for n in names
                if not n.startswith("_") or (self.all_set and n in self.all_set)
            ]
            if public_names:
                is_reexport = True

        imp: dict = {
            "source": source,
            "names": names,
            "line": node.lineno,
            "is_reexport": is_reexport,
        }
        if name_map:
            imp["name_map"] = name_map
        self.imports.append(imp)
        self.generic_visit(node)

    # --- Exports (top-level definitions) ---

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_funcdef(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_funcdef(node)

    def _handle_funcdef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._depth == 0 or (self._depth == 1 and self._class_scope_depth > 0):
            name = node.name
            if self._scope_stack:
                name = f"{self._scope_stack[-1]}.{node.name}"

            if self._is_exported(node.name) or self._is_exported(name):
                exclude = _has_framework_decorator(node.decorator_list)
                self.exports.append({
                    "name": name,
                    "kind": "function",
                    "line": node.lineno,
                    "decorators": _decorator_names(node.decorator_list),
                    "exclude_from_dead_analysis": exclude,
                })

        # Visit body with scope tracking
        self._scope_stack.append(node.name if not self._scope_stack else f"{self._scope_stack[-1]}.{node.name}")
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._depth == 0 and self._is_exported(node.name):
            export: dict[str, Any] = {
                "name": node.name,
                "kind": "class",
                "line": node.lineno,
                "decorators": _decorator_names(node.decorator_list),
                "exclude_from_dead_analysis": _has_framework_decorator(node.decorator_list),
            }
            bases = [n for b in node.bases if (n := _resolve_base_name(b))]
            if bases:
                export["bases"] = bases
            self.exports.append(export)

        self._scope_stack.append(node.name)
        self._class_scope_depth += 1
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1
        self._class_scope_depth -= 1
        self._scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        # Top-level assignments → exports; attribute assignments → member_writes
        if self._depth == 0:
            for target in node.targets:
                if isinstance(target, ast.Name) and self._is_exported(target.id):
                    self.exports.append({
                        "name": target.id,
                        "kind": "constant" if target.id.isupper() else "variable",
                        "line": node.lineno,
                        "decorators": [],
                        "exclude_from_dead_analysis": False,
                    })

        # member_writes: obj.attr = value
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                container = _resolve_callee(target.value)
                if container:
                    self.member_writes.append({
                        "container": container,
                        "member": target.attr,
                        "line": node.lineno,
                    })

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._depth == 0 and node.target and isinstance(node.target, ast.Name):
            name = node.target.id
            if self._is_exported(name):
                self.exports.append({
                    "name": name,
                    "kind": "constant" if name.isupper() else "variable",
                    "line": node.lineno,
                    "decorators": [],
                    "exclude_from_dead_analysis": False,
                })
        self.generic_visit(node)

    # --- Calls ---

    def visit_Call(self, node: ast.Call) -> None:
        callee = _resolve_callee(node.func)
        if callee:
            self.calls.append({
                "from_symbol": _current_scope(self._scope_stack),
                "to": callee,
                "line": node.lineno,
            })
        self.generic_visit(node)

    # --- String literals ---

    def _add_string(
        self,
        value: str,
        line: int,
        usage: str,
        context: str,
        comparison_source: str | None = None,
    ) -> None:
        """Add a string literal if it passes basic filters."""
        if len(value) <= 1:
            return
        if line in self._docstring_lines:
            return
        entry: dict[str, Any] = {
            "value": value,
            "line": line,
            "usage": usage,
            "context": context,
        }
        if comparison_source:
            entry["comparison_source"] = comparison_source
        self.string_literals.append(entry)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Classify string constants by examining their parent node."""
        if not isinstance(node.value, str):
            self.generic_visit(node)
            return

        parent = getattr(node, "_parent", None)
        if parent is None:
            self.generic_visit(node)
            return

        value = node.value
        line = node.lineno

        # Dict value → produced
        if isinstance(parent, ast.Dict):
            if node in parent.values:
                self._add_string(value, line, "produced", "dict value")
            # Skip dict keys — they're structural, not contract strings
            self.generic_visit(node)
            return

        # Equality / membership comparison → checked
        if isinstance(parent, ast.Compare):
            for op in parent.ops:
                if isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                    # Resolve comparison_source from the other side
                    other = None
                    if node is parent.left:
                        # String is on the left, source is the first comparator
                        if parent.comparators:
                            other = _resolve_callee(parent.comparators[0])
                    else:
                        # String is a comparator, source is the left side
                        other = _resolve_callee(parent.left)
                    self._add_string(value, line, "checked", "equality comparison",
                                     comparison_source=other or None)
                    self.generic_visit(node)
                    return
            self.generic_visit(node)
            return

        # Constant assignment: NAME = "string" → defined
        if isinstance(parent, (ast.Assign, ast.AnnAssign)):
            targets = parent.targets if isinstance(parent, ast.Assign) else ([parent.target] if parent.target else [])
            if len(targets) == 1 and isinstance(targets[0], ast.Name):
                self._add_string(value, line, "defined", f"constant {targets[0].id}")
                self.generic_visit(node)
                return

        # Return value → produced
        if isinstance(parent, ast.Return):
            self._add_string(value, line, "produced", "return value")
            self.generic_visit(node)
            return

        # Function call argument → produced
        if isinstance(parent, ast.Call):
            callee = _resolve_callee(parent.func)
            ctx = f"argument to {callee}" if callee else "function argument"
            self._add_string(value, line, "produced", ctx)
            self.generic_visit(node)
            return

        # Keyword argument value → produced
        if isinstance(parent, ast.keyword):
            grandparent = getattr(parent, "_parent", None)
            callee = ""
            if isinstance(grandparent, ast.Call):
                callee = _resolve_callee(grandparent.func)
            ctx = f"keyword argument to {callee}" if callee else "keyword argument"
            self._add_string(value, line, "produced", ctx)
            self.generic_visit(node)
            return

        # Collection literal element → produced
        if isinstance(parent, (ast.List, ast.Tuple, ast.Set)):
            self._add_string(value, line, "produced", "collection element")
            self.generic_visit(node)
            return

        # Default parameter value → produced
        if isinstance(parent, ast.arguments):
            self._add_string(value, line, "produced", "default parameter")
            self.generic_visit(node)
            return

        # Docstring (standalone Expr) — already filtered by _docstring_lines
        if isinstance(parent, ast.Expr):
            # Skip standalone string expressions (docstrings, etc.)
            self.generic_visit(node)
            return

        # f-string parts — skip
        if isinstance(parent, (ast.JoinedStr, ast.FormattedValue)):
            self.generic_visit(node)
            return

        self.generic_visit(node)


class PythonPlugin(LanguagePlugin):
    """Python AST extraction plugin using stdlib ``ast``."""

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".py", ".pyi"})

    def check_available(self, project_root: Path) -> None:
        pass  # stdlib ast, always available

    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        # Filter to Python files
        py_files = [f for f in files if f.suffix in self.extensions]
        if not py_files:
            return {}

        # Build file set for import resolution
        file_set: set[str] = set()
        for f in py_files:
            file_set.add(normalize_path(f, project_root))

        # --- First pass: per-file AST extraction ---
        per_file: dict[str, _FileExtractor] = {}

        for file_path in py_files:
            rel = normalize_path(file_path, project_root)
            try:
                source_code = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning(f"[python] Cannot read {rel}: {e}")
                continue

            # Pre-scan for __all__
            try:
                tree = ast.parse(source_code, filename=rel)
            except SyntaxError as e:
                logger.warning(f"[python] SyntaxError in {rel}: {e}")
                continue

            all_members = _get_all_members(tree)
            is_init = file_path.name == "__init__.py"

            # Annotate parents for string literal context classification
            _annotate_parents(tree)

            extractor = _FileExtractor(
                relative_path=rel,
                is_init=is_init,
                all_members=all_members,
            )
            # Collect docstring lines before visiting
            extractor._docstring_lines = _collect_docstring_lines(tree.body)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    extractor._docstring_lines |= _collect_docstring_lines(node.body)

            extractor.visit(tree)
            per_file[rel] = extractor

        # --- Second pass: cross-file call resolution (shared module) ---
        annotate_call_sites(per_file, file_set)

        # Build result
        result: dict[str, ExtractedFacts] = {}
        for rel, ext in per_file.items():
            result[rel] = ExtractedFacts(
                imports=ext.imports,
                exports=ext.exports,
                calls=ext.calls,
                member_writes=ext.member_writes,
                string_literals=ext.string_literals,
            )

        return result
