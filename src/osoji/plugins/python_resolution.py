"""Cross-file import and call-site resolution for Python plugins.

Pure path/dict logic with zero AST dependence, shared verbatim by the legacy
``ast``-based plugin and the tree-sitter plugin (V1-6a) so the project-wide
``call_sites`` counts stay bit-identical across the migration.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


def normalize_path(path: Path, root: Path) -> str:
    """Normalize a path to forward-slash relative string."""
    return str(path.relative_to(root)).replace("\\", "/")


def resolve_python_import(
    source: str,
    importing_file: str,
    file_set: set[str],
) -> str | None:
    """Resolve a Python import source specifier to a project-relative path.

    Handles relative imports (.foo, ..bar) and absolute imports.
    Returns normalized forward-slash path or None for external packages.
    """
    if source.startswith("."):
        # Relative import
        dots = 0
        for ch in source:
            if ch == ".":
                dots += 1
            else:
                break
        remainder = source[dots:]

        importing_dir = Path(importing_file).parent
        # Go up (dots - 1) directories
        base = importing_dir
        for _ in range(dots - 1):
            base = base.parent

        base_str = str(base).replace("\\", "/")
        if base_str == ".":
            base_str = ""

        if remainder:
            module_path = f"{base_str}/{remainder.replace('.', '/')}" if base_str else remainder.replace(".", "/")
        else:
            module_path = base_str

        return find_python_file(module_path, file_set)

    # Absolute import — try direct path and src/ prefix
    module_path = source.replace(".", "/")
    for prefix in ("", "src/"):
        result = find_python_file(f"{prefix}{module_path}", file_set)
        if result:
            return result

    return None


def find_python_file(candidate_base: str, file_set: set[str]) -> str | None:
    """Try to match a module path to an actual file in the project."""
    candidate_base = candidate_base.rstrip("/")
    if not candidate_base:
        return None

    # Direct match
    if candidate_base in file_set:
        return candidate_base

    # Try .py / .pyi
    for ext in (".py", ".pyi"):
        candidate = candidate_base + ext
        if candidate in file_set:
            return candidate

    # Try __init__.py
    init = f"{candidate_base}/__init__.py"
    if init in file_set:
        return init

    return None


def annotate_call_sites(per_file: dict[str, Any], file_set: set[str]) -> None:
    """Populate ``call_sites`` on every call record (the plugin's second pass).

    ``per_file`` maps relative path -> any object with ``imports`` and
    ``calls`` list attributes in the plugin record shapes; the ``calls``
    records are mutated in place.
    """
    # Build import map: for each file, map local names to (defining_file, original_name)
    import_maps: dict[str, dict[str, tuple[str, str]]] = {}
    for rel, ext in per_file.items():
        imap: dict[str, tuple[str, str]] = {}
        for imp in ext.imports:
            resolved = resolve_python_import(
                imp["source"], rel, file_set
            )
            if not resolved:
                continue
            alias_map = imp.get("name_map", {})
            for name in imp.get("names", []):
                if name == "*":
                    continue
                original = alias_map.get(name, name)
                imap[name] = (resolved, original)
        import_maps[rel] = imap

    # Count call sites per (defining_file, symbol_name)
    call_site_counts: dict[tuple[str, str], int] = defaultdict(int)
    for rel, ext in per_file.items():
        imap = import_maps.get(rel, {})
        for call in ext.calls:
            callee = call["to"]
            # Resolve root of the callee through imports
            root = callee.split(".")[0]
            if root in imap:
                def_file, orig_name = imap[root]
                # Reconstruct the original qualified name
                if "." in callee:
                    remainder = callee[len(root):]
                    resolved_name = orig_name + remainder
                else:
                    resolved_name = orig_name
                call_site_counts[(def_file, resolved_name)] += 1
            else:
                # Unresolved call — assume same-file or external/builtin
                call_site_counts[(rel, callee)] += 1

    # Populate call_sites on calls records
    for rel, ext in per_file.items():
        imap = import_maps.get(rel, {})
        for call in ext.calls:
            callee = call["to"]
            root = callee.split(".")[0]
            if root in imap:
                def_file, orig_name = imap[root]
                if "." in callee:
                    remainder = callee[len(root):]
                    resolved_name = orig_name + remainder
                else:
                    resolved_name = orig_name
                count = call_site_counts.get((def_file, resolved_name), 0)
            else:
                count = call_site_counts.get((rel, callee), 0)
            call["call_sites"] = count
