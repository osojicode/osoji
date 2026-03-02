"""Structured facts database — loads .facts.json files and provides queries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config


@dataclass
class FileFacts:
    """Parsed facts for a single file (source or documentation).

    For source files: all fields populated by LLM extraction.
    For doc files: ``imports`` stores source file references (with context),
    ``exports``/``calls``/``string_literals`` are empty.
    """

    source: str
    source_hash: str
    imports: list[dict] = field(default_factory=list)
    exports: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    string_literals: list[dict] = field(default_factory=list)
    # Doc-specific fields (None for source files):
    classification: str | None = None
    topics: list[str] | None = None


def _only_dicts(items: list) -> list[dict]:
    """Filter a list to keep only dict entries, discarding malformed LLM output."""
    return [x for x in items if isinstance(x, dict)]


class FactsDB:
    """In-memory database of structured facts extracted during shadow generation.

    Loads all .facts.json files from .docstar/facts/ and provides query methods
    for import graphs, export analysis, and string contract checking.
    """

    def __init__(self, config: Config):
        self._files: dict[str, FileFacts] = {}
        self._config = config
        self._load(config)

    def _load(self, config: Config) -> None:
        facts_dir = config.root_path / ".docstar" / "facts"
        if not facts_dir.exists():
            return
        for facts_file in facts_dir.rglob("*.facts.json"):
            try:
                data = json.loads(facts_file.read_text(encoding="utf-8"))
                source = data.get("source", "")
                if not source:
                    continue
                source_norm = source.replace("\\", "/")
                self._files[source_norm] = FileFacts(
                    source=source_norm,
                    source_hash=data.get("source_hash", ""),
                    imports=_only_dicts(data.get("imports", [])),
                    exports=_only_dicts(data.get("exports", [])),
                    calls=_only_dicts(data.get("calls", [])),
                    string_literals=_only_dicts(data.get("string_literals", [])),
                    classification=data.get("classification"),
                    topics=data.get("topics"),
                )
            except (json.JSONDecodeError, KeyError):
                continue

    def get_file(self, path: str) -> FileFacts | None:
        """Get facts for a specific file path (forward-slash normalized)."""
        return self._files.get(path.replace("\\", "/"))

    def all_files(self) -> list[str]:
        """Return all file paths with facts data."""
        return list(self._files.keys())

    def _resolve_import_source(self, importing_file: str, source_specifier: str) -> str | None:
        """Resolve an import source specifier to a project-relative file path.

        Returns None for external packages (not found in project).
        """
        # Relative imports (., ..)
        if source_specifier.startswith("."):
            importing_dir = str(Path(importing_file).parent).replace("\\", "/")
            if importing_dir == ".":
                importing_dir = ""

            # Handle multiple dots (.., ..., etc.)
            parts = source_specifier.split("/")
            if len(parts) == 1 and not source_specifier.startswith("./"):
                # Python-style dotted relative import: ..foo.bar
                dots = 0
                for ch in source_specifier:
                    if ch == ".":
                        dots += 1
                    else:
                        break
                remainder = source_specifier[dots:].replace(".", "/")
                # Go up (dots - 1) directories
                base = Path(importing_dir)
                for _ in range(dots - 1):
                    base = base.parent
                base_str = str(base).replace("\\", "/")
                if base_str == ".":
                    base_str = ""
                candidate_base = f"{base_str}/{remainder}" if base_str else remainder
            else:
                # JS-style path relative import: ./foo, ../bar
                resolved = (Path(importing_dir) / source_specifier).resolve()
                try:
                    candidate_base = str(resolved.relative_to(Path.cwd())).replace("\\", "/")
                except ValueError:
                    # Fall back to simple string joining
                    candidate_base = str(Path(importing_dir) / source_specifier).replace("\\", "/")

            return self._find_file(candidate_base)

        # Absolute/package imports — check if first segment matches a project directory
        segments = source_specifier.replace(".", "/").split("/")
        first_segment = segments[0]

        # Try direct path match (e.g., "docstar.facts" -> "src/docstar/facts.py")
        for known_file in self._files:
            # Check if the import maps to a known file
            known_parts = known_file.replace("/", ".").replace(".py", "").replace(".ts", "").replace(".js", "")
            if known_parts.endswith(source_specifier.replace("/", ".")):
                return known_file

        # Try src/<first_segment>/... pattern
        rest = "/".join(segments[1:]) if len(segments) > 1 else ""
        for prefix in ["", "src/"]:
            if rest:
                candidate = f"{prefix}{first_segment}/{rest}"
            else:
                candidate = f"{prefix}{first_segment}"
            match = self._find_file(candidate)
            if match:
                return match

        return None

    def _find_file(self, candidate_base: str) -> str | None:
        """Try to find a project file matching candidate_base with common extensions/index files."""
        candidate_base = candidate_base.rstrip("/")

        # Exact match
        if candidate_base in self._files:
            return candidate_base

        # Try common extensions
        for ext in [".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"]:
            candidate = candidate_base + ext
            if candidate in self._files:
                return candidate

        # Try index files
        for index in ["__init__.py", "index.ts", "index.js", "index.tsx", "mod.rs"]:
            candidate = f"{candidate_base}/{index}"
            if candidate in self._files:
                return candidate

        return None

    def is_doc(self, path: str) -> bool:
        """Check if a facts entry represents a documentation file."""
        facts = self._files.get(path.replace("\\", "/"))
        return facts is not None and facts.classification is not None

    def doc_files(self) -> list[str]:
        """Return paths of all documentation files with facts data."""
        return [p for p, f in self._files.items() if f.classification is not None]

    def docs_referencing(self, source_path: str) -> list[str]:
        """Return doc file paths whose imports reference the given source file.

        Doc files store source references in the ``imports`` field using the
        ``source`` key.  This method checks for exact matches against the
        normalised *source_path*.
        """
        source_norm = source_path.replace("\\", "/")
        result: list[str] = []
        for file_path, facts in self._files.items():
            if facts.classification is None:
                continue  # skip source files
            for imp in facts.imports:
                if imp.get("source", "").replace("\\", "/") == source_norm:
                    result.append(file_path)
                    break
        return result

    def importers_of(self, source_path: str) -> list[str]:
        """Return files that import from the given path."""
        source_norm = source_path.replace("\\", "/")
        importers: list[str] = []
        for file_path, facts in self._files.items():
            if file_path == source_norm:
                continue
            for imp in facts.imports:
                resolved = self._resolve_import_source(file_path, imp.get("source", ""))
                if resolved == source_norm:
                    importers.append(file_path)
                    break
        return importers

    def imports_of(self, file_path: str) -> list[str]:
        """Return project files that this file imports from."""
        file_norm = file_path.replace("\\", "/")
        facts = self._files.get(file_norm)
        if not facts:
            return []
        result: list[str] = []
        for imp in facts.imports:
            resolved = self._resolve_import_source(file_norm, imp.get("source", ""))
            if resolved and resolved in self._files:
                result.append(resolved)
        return list(set(result))

    def exported_names(self, file_path: str) -> set[str]:
        """Return set of exported symbol names for a file."""
        file_norm = file_path.replace("\\", "/")
        facts = self._files.get(file_norm)
        if not facts:
            return set()
        return {e["name"] for e in facts.exports if "name" in e}

    def unused_exports(self) -> list[tuple[str, str]]:
        """Return (file, name) pairs for exports never imported anywhere."""
        # Build set of all imported names per source file
        imported_from: dict[str, set[str]] = {}
        for file_path, facts in self._files.items():
            for imp in facts.imports:
                resolved = self._resolve_import_source(file_path, imp.get("source", ""))
                if resolved:
                    names = set(imp.get("names", []))
                    imported_from.setdefault(resolved, set()).update(names)

        unused: list[tuple[str, str]] = []
        for file_path, facts in self._files.items():
            imported_names = imported_from.get(file_path, set())
            # If "*" is imported, all exports are considered used
            if "*" in imported_names:
                continue
            for export in facts.exports:
                name = export.get("name", "")
                if name and name not in imported_names:
                    unused.append((file_path, name))
        return unused

    def strings_by_usage(self, usage: str, kind: str | None = None) -> dict[str, set[str]]:
        """Return file -> set of string values filtered by usage and optionally kind."""
        result: dict[str, set[str]] = {}
        for file_path, facts in self._files.items():
            for sl in facts.string_literals:
                if sl.get("usage") != usage:
                    continue
                if kind is not None and sl.get("kind") != kind:
                    continue
                result.setdefault(file_path, set()).add(sl.get("value", ""))
        return result

    def string_entries_by_usage(self, usage: str, kind: str | None = None) -> dict[str, list[dict]]:
        """Return file -> list of full string literal entries filtered by usage and optionally kind."""
        result: dict[str, list[dict]] = {}
        for file_path, facts in self._files.items():
            for sl in facts.string_literals:
                if sl.get("usage") != usage:
                    continue
                if kind is not None and sl.get("kind") != kind:
                    continue
                result.setdefault(file_path, []).append(sl)
        return result

    def build_import_graph(self) -> dict[str, set[str]]:
        """Build file -> set of imported files graph."""
        graph: dict[str, set[str]] = {}
        for file_path in self._files:
            graph[file_path] = set(self.imports_of(file_path))
        return graph

    def unreachable_files(self, entry_points: set[str]) -> set[str]:
        """Find files not reachable from any entry point via imports."""
        graph = self.build_import_graph()
        # Build bidirectional adjacency for reachability
        adjacency: dict[str, set[str]] = {}
        for src, targets in graph.items():
            adjacency.setdefault(src, set()).update(targets)
            for t in targets:
                adjacency.setdefault(t, set()).add(src)

        # BFS from entry points
        visited: set[str] = set()
        queue = list(entry_points & set(self._files.keys()))
        visited.update(queue)
        while queue:
            current = queue.pop(0)
            for neighbor in adjacency.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return set(self._files.keys()) - visited
