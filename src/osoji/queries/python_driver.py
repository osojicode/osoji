"""Tree-sitter Python plugin (V1-6a) — port of the ``ast``-based extractor.

Port, not redesign: this driver is a transliteration of the legacy
``plugins/_legacy_python_ast._FileExtractor`` so its output is bit-identical
(``tests/test_plugin_python_parity.py`` pins this against a committed golden).
The ``.scm`` queries under ``queries/python/`` select the nodes of interest;
this driver carries the semantics — scope tracking, ``__all__`` gating,
parent-based string classification — because tree-sitter queries cannot.

Deliberate legacy quirks preserved (do not "fix" without an A/B):
- the scope stack pushes dotted names for functions but *bare* names for
  classes (so methods report ``Class.method``, resetting outer chains);
- decorators are walked *after* the definition body (ast field order), so
  decorator calls carry the decorated symbol's scope;
- chained assignments (``a = b = "v"``) export every target but produce no
  ``defined`` string record (multi-target rule);
- membership tuples (``x in ("a", "b")``) classify as collection elements,
  not ``checked``.
"""

from __future__ import annotations

import ast as _ast  # literal_eval only — recovers exact ast string values
import logging
from pathlib import Path
from typing import Any

from ..plugins.base import ExtractedFacts, LanguagePlugin, PluginUnavailableError
from ..plugins.python_resolution import annotate_call_sites, normalize_path

logger = logging.getLogger(__name__)

# Verbatim from the legacy plugin: decorators indicating framework/convention
# usage — these symbols get ``exclude_from_dead_analysis: True``.
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

_INSTALL_HINT = "pip install tree-sitter tree-sitter-python"


def _load_language():
    """Import tree-sitter lazily so osoji imports without the wheels."""

    try:
        import tree_sitter_python
        from tree_sitter import Language
    except ImportError as exc:  # pragma: no cover - exercised via check_available
        raise PluginUnavailableError(
            f"tree-sitter runtime not importable: {exc}", install_hint=_INSTALL_HINT
        ) from exc
    return Language(tree_sitter_python.language())


class _TSFileExtractor:
    """Single-file extraction over a tree-sitter CST (mirror of _FileExtractor)."""

    def __init__(
        self,
        *,
        src: bytes,
        is_init: bool,
        all_members: list[str] | None,
        capture_ids: dict[str, set[int]],
    ):
        self.src = src
        self.is_init = is_init
        self.all_members = all_members
        self.all_set: set[str] | None = set(all_members) if all_members is not None else None
        self.capture_ids = capture_ids

        self.imports: list[dict[str, Any]] = []
        self.exports: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.member_writes: list[dict[str, Any]] = []
        self.string_literals: list[dict[str, Any]] = []

        self._scope_stack: list[str] = []
        self._depth = 0
        self._class_scope_depth = 0
        self._docstring_lines: set[int] = set()

    # -- shared helpers ------------------------------------------------------

    def _text(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    @staticmethod
    def _line(node) -> int:
        return node.start_point[0] + 1

    @staticmethod
    def _unwrap_parens(node):
        while node is not None and node.type == "parenthesized_expression":
            inner = node.named_children
            node = inner[0] if inner else None
        return node

    def _dotted(self, node, *, through_call: bool) -> str:
        """Mirror of _decorator_name (through_call) / _resolve_callee."""

        node = self._unwrap_parens(node)
        if node is None:
            return ""
        if node.type == "identifier":
            return self._text(node)
        if node.type == "attribute":
            prefix = self._dotted(node.child_by_field_name("object"), through_call=through_call)
            attr_node = node.child_by_field_name("attribute")
            attr = self._text(attr_node) if attr_node is not None else ""
            if prefix:
                return f"{prefix}.{attr}"
            return attr
        if node.type == "call" and through_call:
            return self._dotted(node.child_by_field_name("function"), through_call=True)
        return ""

    def _is_exported(self, name: str) -> bool:
        if self.all_set is not None:
            return name in self.all_set
        if name.startswith("_"):
            return False
        return True

    def _current_scope(self) -> str:
        return self._scope_stack[-1] if self._scope_stack else "<module>"

    def _decorator_exprs(self, decorator_nodes) -> list:
        exprs = []
        for dec in decorator_nodes:
            inner = dec.named_children
            if inner:
                exprs.append(inner[0])
        return exprs

    def _decorator_names(self, decorator_nodes) -> list[str]:
        return [
            n
            for dec in self._decorator_exprs(decorator_nodes)
            if (n := self._dotted(dec, through_call=True))
        ]

    def _has_framework_decorator(self, decorator_nodes) -> bool:
        for name in self._decorator_names(decorator_nodes):
            if name in _FRAMEWORK_DECORATOR_NAMES:
                return True
            if any(name.endswith(suffix) for suffix in _FRAMEWORK_DECORATOR_SUFFIXES):
                return True
        return False

    # -- docstrings -----------------------------------------------------------

    @staticmethod
    def _first_statement_string(body):
        if body is None:
            return None
        for child in body.named_children:
            if child.type == "comment":
                continue
            if child.type == "expression_statement":
                inner = child.named_children
                if inner and inner[0].type == "string":
                    return inner[0]
            return None
        return None

    def collect_docstrings(self, root) -> None:
        candidates = [root]
        candidates.extend(
            node for node in _iter_nodes(root)
            if node.id in self.capture_ids["function"] or node.id in self.capture_ids["class"]
        )
        for node in candidates:
            body = node if node.type == "module" else node.child_by_field_name("body")
            doc = self._first_statement_string(body)
            if doc is not None:
                self._docstring_lines.add(self._line(doc))

    # -- walk ------------------------------------------------------------------

    def extract(self, root) -> None:
        self.collect_docstrings(root)
        for child in root.named_children:
            self._walk(child)

    def _walk(self, node) -> None:
        node_id = node.id
        if node_id in self.capture_ids["import"]:
            self._handle_import(node)
            return
        if node_id in self.capture_ids["import_from"]:
            self._handle_import_from(node)
            return
        if node_id in self.capture_ids["import_future"]:
            self._handle_future_import(node)
            return
        if node_id in self.capture_ids["decorated"]:
            self._handle_decorated(node)
            return
        if node_id in self.capture_ids["function"]:
            self._handle_funcdef(node, decorator_nodes=[])
            return
        if node_id in self.capture_ids["class"]:
            self._handle_classdef(node, decorator_nodes=[])
            return
        if node_id in self.capture_ids["assignment"]:
            self._handle_assignment(node)
            return
        if node_id in self.capture_ids["call"]:
            self._handle_call(node)
            return
        if node_id in self.capture_ids["string"] or node_id in self.capture_ids["concat"]:
            self._handle_string(node)
            return
        if node.type == "comment":
            return
        if node.type == "conditional_expression":
            # ast.IfExp field order is (test, body, orelse); source order is
            # body-if-test-else-orelse. Mirror ast so record order matches.
            operands = node.named_children
            if len(operands) == 3:
                self._walk(operands[1])
                self._walk(operands[0])
                self._walk(operands[2])
                return
        for child in node.named_children:
            self._walk(child)

    # -- imports ---------------------------------------------------------------

    def _import_reexport(self, local: str) -> bool:
        return (
            self.is_init
            and not local.startswith("_")
            and (self.all_set is None or local in self.all_set)
        )

    def _handle_import(self, node) -> None:
        line = self._line(node)
        for child in node.named_children:
            if child.type == "dotted_name":
                source = self._text(child)
                local = source
                alias = None
            elif child.type == "aliased_import":
                source = self._text(child.child_by_field_name("name"))
                alias = self._text(child.child_by_field_name("alias"))
                local = alias
            else:
                continue
            imp: dict = {
                "source": source,
                "names": [local],
                "line": line,
                "is_reexport": self._import_reexport(local),
            }
            if alias:
                imp["name_map"] = {local: source}
            self.imports.append(imp)

    def _import_from_names(self, node, module_node):
        names: list[str] = []
        name_map: dict[str, str] = {}
        module_id = module_node.id if module_node is not None else None
        for child in node.named_children:
            if child.id == module_id:
                continue
            if child.type == "wildcard_import":
                names.append("*")
            elif child.type == "dotted_name":
                names.append(self._text(child))
            elif child.type == "aliased_import":
                original = self._text(child.child_by_field_name("name"))
                local = self._text(child.child_by_field_name("alias"))
                names.append(local)
                name_map[local] = original
        return names, name_map

    def _finish_import_from(self, source: str, names, name_map, line: int) -> None:
        is_reexport = False
        if self.is_init:
            public_names = [
                n for n in names
                if not n.startswith("_") or (self.all_set and n in self.all_set)
            ]
            if public_names:
                is_reexport = True
        imp: dict = {
            "source": source,
            "names": names,
            "line": line,
            "is_reexport": is_reexport,
        }
        if name_map:
            imp["name_map"] = name_map
        self.imports.append(imp)

    def _handle_import_from(self, node) -> None:
        module_node = node.child_by_field_name("module_name")
        source = self._text(module_node) if module_node is not None else ""
        names, name_map = self._import_from_names(node, module_node)
        self._finish_import_from(source, names, name_map, self._line(node))

    def _handle_future_import(self, node) -> None:
        names, name_map = self._import_from_names(node, None)
        self._finish_import_from("__future__", names, name_map, self._line(node))

    # -- definitions -------------------------------------------------------------

    def _handle_decorated(self, node) -> None:
        decorator_nodes = [c for c in node.named_children if c.type == "decorator"]
        defn = node.child_by_field_name("definition")
        if defn is None:
            return
        if defn.id in self.capture_ids["function"]:
            self._handle_funcdef(defn, decorator_nodes=decorator_nodes)
        elif defn.id in self.capture_ids["class"]:
            self._handle_classdef(defn, decorator_nodes=decorator_nodes)

    def _push_function_scope(self, name: str) -> None:
        self._scope_stack.append(
            name if not self._scope_stack else f"{self._scope_stack[-1]}.{name}"
        )

    def _handle_funcdef(self, node, *, decorator_nodes) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        bare = self._text(name_node)

        if self._depth == 0 or (self._depth == 1 and self._class_scope_depth > 0):
            name = bare
            if self._scope_stack:
                name = f"{self._scope_stack[-1]}.{bare}"
            if self._is_exported(bare) or self._is_exported(name):
                self.exports.append({
                    "name": name,
                    "kind": "function",
                    "line": self._line(node),
                    "decorators": self._decorator_names(decorator_nodes),
                    "exclude_from_dead_analysis": self._has_framework_decorator(decorator_nodes),
                })

        self._push_function_scope(bare)
        self._depth += 1
        # ast field order: args, body, decorator_list, returns
        params = node.child_by_field_name("parameters")
        if params is not None:
            for child in params.named_children:
                self._walk(child)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.named_children:
                self._walk(child)
        for expr in self._decorator_exprs(decorator_nodes):
            self._walk(expr)
        return_type = node.child_by_field_name("return_type")
        if return_type is not None:
            self._walk(return_type)
        self._depth -= 1
        self._scope_stack.pop()

    def _handle_classdef(self, node, *, decorator_nodes) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        superclasses = node.child_by_field_name("superclasses")

        if self._depth == 0 and self._is_exported(name):
            export: dict[str, Any] = {
                "name": name,
                "kind": "class",
                "line": self._line(node),
                "decorators": self._decorator_names(decorator_nodes),
                "exclude_from_dead_analysis": self._has_framework_decorator(decorator_nodes),
            }
            bases = []
            if superclasses is not None:
                bases = [
                    b for base in superclasses.named_children
                    if base.type != "keyword_argument"
                    and (b := self._dotted(base, through_call=True))
                ]
            if bases:
                export["bases"] = bases
            self.exports.append(export)

        self._scope_stack.append(name)
        self._class_scope_depth += 1
        self._depth += 1
        # ast field order: bases, keywords, body, decorator_list
        if superclasses is not None:
            for child in superclasses.named_children:
                self._walk(child)
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.named_children:
                self._walk(child)
        for expr in self._decorator_exprs(decorator_nodes):
            self._walk(expr)
        self._depth -= 1
        self._class_scope_depth -= 1
        self._scope_stack.pop()

    # -- assignments ---------------------------------------------------------------

    @staticmethod
    def _flatten_assignment(node):
        """Return (targets, value) mirroring ast's multi-target Assign."""

        targets = []
        value = node
        while value is not None and value.type == "assignment":
            left = value.child_by_field_name("left")
            if left is not None:
                targets.append(left)
            value = value.child_by_field_name("right")
        return targets, value

    def _handle_assignment(self, node) -> None:
        targets, value = self._flatten_assignment(node)
        line = self._line(node)

        if self._depth == 0:
            for target in targets:
                if target.type == "identifier":
                    name = self._text(target)
                    if self._is_exported(name):
                        self.exports.append({
                            "name": name,
                            "kind": "constant" if name.isupper() else "variable",
                            "line": line,
                            "decorators": [],
                            "exclude_from_dead_analysis": False,
                        })

        # ast records member_writes for plain Assign only, never AnnAssign
        if node.child_by_field_name("type") is None:
            for target in targets:
                if target.type == "attribute":
                    container = self._dotted(
                        target.child_by_field_name("object"), through_call=False
                    )
                    if container:
                        member_node = target.child_by_field_name("attribute")
                        self.member_writes.append({
                            "container": container,
                            "member": self._text(member_node) if member_node is not None else "",
                            "line": line,
                        })

        # ast field order: targets, (annotation,) value
        for target in targets:
            for child in target.named_children:
                self._walk(child)
        type_node = node.child_by_field_name("type")
        if type_node is not None:
            self._walk(type_node)
        if value is not None:
            self._walk(value)

    # -- calls -----------------------------------------------------------------------

    def _handle_call(self, node) -> None:
        func = node.child_by_field_name("function")
        callee = self._dotted(func, through_call=False)
        if callee:
            self.calls.append({
                "from_symbol": self._current_scope(),
                "to": callee,
                "line": self._line(node),
            })
        # ast field order: func, args, keywords
        if func is not None:
            self._walk(func)
        arguments = node.child_by_field_name("arguments")
        if arguments is not None:
            for child in arguments.named_children:
                self._walk(child)

    # -- strings -----------------------------------------------------------------------

    def _add_string(
        self,
        value: str,
        line: int,
        usage: str,
        context: str,
        comparison_source: str | None = None,
    ) -> None:
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

    def _walk_interpolations(self, node) -> None:
        for child in node.named_children:
            if child.type == "interpolation":
                for inner in child.named_children:
                    self._walk(inner)
            elif child.type == "string":
                self._walk_interpolations(child)

    def _string_value(self, node) -> str | None:
        """Recover the evaluated string value, or None to skip (f/bytes/invalid).

        Wrapped in parentheses so multiline implicit concatenations evaluate;
        f-strings still fail (mirroring the ast JoinedStr skip) and bytes are
        rejected by the isinstance check.
        """

        try:
            value = _ast.literal_eval(f"({self._text(node)})")
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None
        if not isinstance(value, str):
            return None
        return value

    def _effective_parent(self, node):
        parent = node.parent
        while parent is not None and parent.type == "parenthesized_expression":
            parent = parent.parent
        return parent

    @staticmethod
    def _top_under(node, parent):
        """Climb paren wrappers: the ancestor of ``node`` that is a direct child of ``parent``."""

        top = node
        while top.parent is not None and top.parent.id != parent.id:
            top = top.parent
        return top

    def _handle_string(self, node) -> None:
        parent = node.parent
        if parent is not None and parent.type == "concatenated_string":
            return  # handled at the concatenation node

        value = self._string_value(node)
        if value is None:
            self._walk_interpolations(node)
            return
        line = self._line(node)
        self._classify_string(node, value, line)

    def _classify_string(self, node, value: str, line: int) -> None:
        parent = self._effective_parent(node)
        if parent is None:
            return
        ptype = parent.type
        # ast strips parentheses; compare positions against the paren top
        node = self._top_under(node, parent)

        # Dict value -> produced; dict keys are structural, skipped
        if ptype == "pair":
            grandparent = parent.parent
            value_node = parent.child_by_field_name("value")
            if (
                grandparent is not None
                and grandparent.type == "dictionary"
                and value_node is not None
                and value_node.id == node.id
            ):
                self._add_string(value, line, "produced", "dict value")
            return

        # Equality / membership comparison -> checked
        if ptype == "comparison_operator":
            operator_texts = {
                self._text(child) for child in parent.children if not child.is_named
            }
            if operator_texts & {"==", "!=", "in", "not in"}:
                operands = list(parent.named_children)
                other = None
                if operands and operands[0].id == node.id:
                    if len(operands) > 1:
                        other = self._dotted(operands[1], through_call=False)
                else:
                    other = self._dotted(operands[0], through_call=False) if operands else None
                self._add_string(value, line, "checked", "equality comparison",
                                 comparison_source=other or None)
            return

        # Constant assignment: NAME = "string" -> defined
        if ptype == "assignment":
            if parent.parent is not None and parent.parent.type == "assignment":
                return  # chained assignment: ast sees multiple targets
            right = parent.child_by_field_name("right")
            if right is None or right.id != node.id:
                return
            left = parent.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                self._add_string(value, line, "defined", f"constant {self._text(left)}")
            return

        # Return value -> produced
        if ptype == "return_statement":
            self._add_string(value, line, "produced", "return value")
            return

        # Positional call argument -> produced
        if ptype == "argument_list":
            call = parent.parent
            if call is not None and call.type == "call":
                callee = self._dotted(
                    call.child_by_field_name("function"), through_call=False
                )
                ctx = f"argument to {callee}" if callee else "function argument"
                self._add_string(value, line, "produced", ctx)
            return

        # Keyword argument value -> produced
        if ptype == "keyword_argument":
            callee = ""
            arg_list = parent.parent
            if arg_list is not None and arg_list.type == "argument_list":
                call = arg_list.parent
                if call is not None and call.type == "call":
                    callee = self._dotted(
                        call.child_by_field_name("function"), through_call=False
                    )
            ctx = f"keyword argument to {callee}" if callee else "keyword argument"
            self._add_string(value, line, "produced", ctx)
            return

        # Collection literal element -> produced (expression_list is ast.Tuple)
        if ptype in ("list", "tuple", "set", "expression_list"):
            self._add_string(value, line, "produced", "collection element")
            return

        # Multi-element subscript (Literal["a", "b"]): ast wraps the elements
        # in a Tuple -> collection element; a single-element subscript keeps
        # the bare Subscript parent -> skipped.
        if ptype == "subscript":
            subscript_children = [
                c for c in parent.children_by_field_name("subscript")
            ]
            if len(subscript_children) > 1:
                self._add_string(value, line, "produced", "collection element")
            return

        # Type-annotation strings (forward references). ast has no type
        # context: dict[str, "X"] puts "X" in a Tuple -> collection element
        # (single-parameter generics keep the Subscript parent -> skipped),
        # and a bare quoted annotation on an assignment surfaces as the
        # AnnAssign parent -> the 'defined' branch applies even though the
        # string is the annotation, not the value (legacy quirk, preserved).
        if ptype == "type":
            outer = parent.parent
            if outer is not None and outer.type == "type_parameter":
                type_children = [
                    c for c in outer.named_children if c.type == "type"
                ]
                if len(type_children) > 1:
                    self._add_string(value, line, "produced", "collection element")
                return
            if outer is not None and outer.type == "assignment":
                if outer.parent is not None and outer.parent.type == "assignment":
                    return
                left = outer.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    self._add_string(value, line, "defined", f"constant {self._text(left)}")
                return
            return

        # Default parameter value -> produced
        if ptype in ("default_parameter", "typed_default_parameter"):
            value_node = parent.child_by_field_name("value")
            if value_node is not None and value_node.id == node.id:
                self._add_string(value, line, "produced", "default parameter")
            return

        # Standalone expression strings (docstrings etc.) and everything else: skip


def _iter_nodes(root):
    """Yield every node in the tree (document order)."""

    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _get_all_members(extractor: _TSFileExtractor, root) -> list[str] | None:
    """Mirror of the legacy module-level __all__ pre-scan."""

    for stmt in root.named_children:
        if stmt.type != "expression_statement":
            continue
        exprs = stmt.named_children
        if not exprs:
            continue
        expr = exprs[0]
        if expr.type == "assignment":
            targets, value = _TSFileExtractor._flatten_assignment(expr)
            if any(
                t.type == "identifier" and extractor._text(t) == "__all__"
                for t in targets
            ):
                if value is None:
                    continue  # annotation-only, no value to extract
                return _extract_string_list(extractor, value)
        elif expr.type == "augmented_assignment":
            left = expr.child_by_field_name("left")
            if left is not None and left.type == "identifier" \
                    and extractor._text(left) == "__all__":
                return None  # __all__ += [...] — can't reliably resolve
    return None


def _extract_string_list(extractor: _TSFileExtractor, node) -> list[str] | None:
    node = _TSFileExtractor._unwrap_parens(node)
    if node is None or node.type not in ("list", "tuple"):
        return None
    result: list[str] = []
    for child in node.named_children:
        if child.type == "comment":
            continue
        if child.type != "string":
            return None
        value = extractor._string_value(child)
        if value is None:
            return None
        result.append(value)
    return result


class PythonPlugin(LanguagePlugin):
    """Python extraction plugin backed by tree-sitter queries."""

    def __init__(self) -> None:
        self._language = None
        self._parser = None
        self._queries = None

    @property
    def name(self) -> str:
        return "python"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".py", ".pyi"})

    def check_available(self, project_root: Path) -> None:
        self._ensure_runtime()

    def _ensure_runtime(self) -> None:
        if self._parser is not None:
            return
        from tree_sitter import Parser

        from . import load_queries

        self._language = _load_language()
        self._parser = Parser(self._language)
        self._queries = load_queries("python", self._language)

    def _capture_ids(self, root) -> dict[str, set[int]]:
        from tree_sitter import QueryCursor

        ids: dict[str, set[int]] = {
            "import": set(), "import_from": set(), "import_future": set(),
            "function": set(), "class": set(), "decorated": set(),
            "assignment": set(), "augmented": set(),
            "call": set(),
            "string": set(), "concat": set(),
            "member_write_target": set(),
        }
        for query in self._queries.values():
            captures = QueryCursor(query).captures(root)
            for capture_name, nodes in captures.items():
                bucket = ids.setdefault(capture_name, set())
                bucket.update(node.id for node in nodes)
        return ids

    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        py_files = [f for f in files if f.suffix in self.extensions]
        if not py_files:
            return {}
        self._ensure_runtime()

        file_set: set[str] = set()
        for f in py_files:
            file_set.add(normalize_path(f, project_root))

        # --- First pass: per-file CST extraction ---
        per_file: dict[str, _TSFileExtractor] = {}

        for file_path in py_files:
            rel = normalize_path(file_path, project_root)
            try:
                source_code = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning(f"[python] Cannot read {rel}: {e}")
                continue

            src = source_code.encode("utf-8")
            tree = self._parser.parse(src)
            root = tree.root_node
            if root.has_error:
                logger.warning(f"[python] Parse error in {rel}: skipping file")
                continue

            capture_ids = self._capture_ids(root)
            prescan = _TSFileExtractor(
                src=src, is_init=False, all_members=None, capture_ids=capture_ids
            )
            all_members = _get_all_members(prescan, root)
            extractor = _TSFileExtractor(
                src=src,
                is_init=file_path.name == "__init__.py",
                all_members=all_members,
                capture_ids=capture_ids,
            )
            extractor.extract(root)
            per_file[rel] = extractor

        # --- Second pass: cross-file call resolution (shared module) ---
        annotate_call_sites(per_file, file_set)

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
