"""Plugin interface and shared types for language-specific AST extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractedFacts:
    """AST-extracted facts for a single file.

    string_literals is optional — ``None`` means the plugin does not extract
    strings (LLM handles it alone); an empty list means the plugin found none.
    The LLM still provides semantic ``kind`` classification; AST provides
    structural fields (usage, comparison_source).
    """

    imports: list[dict[str, Any]] = field(default_factory=list)
    exports: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    member_writes: list[dict[str, Any]] = field(default_factory=list)
    string_literals: list[dict[str, Any]] | None = None

    def to_file_facts_dict(self, source: str, source_hash: str) -> dict:
        """Convert to a dict compatible with the facts JSON schema."""
        d: dict[str, Any] = {
            "source": source,
            "source_hash": source_hash,
            "imports": self.imports,
            "exports": self.exports,
            "calls": self.calls,
            "member_writes": self.member_writes,
            "extraction_method": "ast",
        }
        if self.string_literals is not None:
            d["string_literals"] = self.string_literals
        return d


# Structure facts (``LanguagePlugin.extract_structure``): what a file
# *declares* and *names*, in a language-neutral shape, for the code-claim
# registries (factreg.SymbolRegistry, claims_code.py). One dict per file:
#
#   imports:       [{specifier, names, name_map, default, namespace, line, reexport, star, type_only}]
#   declarations:  [{name, kind, exported, line, members?, open?, extends?, implements?, annotation?, params?}]
#                  kind: enum | interface | type | class | object | function | variable
#                  members: [{name, kind, optional?, params?, required_params?, signature?, static?, param_list?, line?}]
#                  open: True when the member set is not closed (index signature, spread, computed key)
#   member_refs:   [{object, member, line, optional, call}]     -- `object.member` where object is an identifier
#   calls:         [{callee, member, line, args: [{index, keys, spread}]}]  -- only object-literal arguments
#   local_exports: [{name, alias}]                              -- `export { x as y }` without a module
#
# Everything is syntactic: no type resolution, no dependency installed. The
# plugin also owns its module-specifier conventions (``module_candidates``)
# and its notion of workspace packages (``workspace_packages``).


class PluginUnavailableError(Exception):
    """Raised when a plugin's external tooling is not installed."""

    def __init__(self, message: str, install_hint: str):
        super().__init__(message)
        self.install_hint = install_hint


class FactsExtractionError(Exception):
    """Raised when extraction fails (parse error, subprocess crash, etc.)."""


class LanguagePlugin(ABC):
    """Abstract base class for language-specific AST extraction plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this plugin (e.g. 'python')."""
        ...

    @property
    @abstractmethod
    def extensions(self) -> frozenset[str]:
        """File extensions this plugin handles (e.g. frozenset({'.py', '.pyi'}))."""
        ...

    def check_available(self, project_root: Path) -> None:
        """Raise PluginUnavailableError if external tooling is missing.

        Default implementation assumes no external dependencies (e.g. stdlib AST).
        """
        pass

    @abstractmethod
    def extract_project_facts(
        self, project_root: Path, files: list[Path]
    ) -> dict[str, ExtractedFacts]:
        """Extract facts for all applicable files in the project.

        Args:
            project_root: Absolute path to the repository root.
            files: Already-filtered file list from osoji's walker.
                   The plugin should filter to its own ``extensions``.

        Returns:
            Dict mapping normalized relative paths (forward-slash) to ExtractedFacts.
        """
        ...

    def extract_structure(self, project_root: Path, files: list[Path]) -> dict[str, dict] | None:
        """Structure facts for the code-claim registries (see the schema above).

        Returns None when the plugin has no parser for them; the registries
        then simply do not cover this language.
        """
        return None

    def module_candidates(self, base: str) -> list[str]:
        """Repository-relative paths a normalised module specifier may denote.

        ``base`` is the specifier already joined to the importing file's
        directory (or a workspace package's source directory); the plugin
        adds its language's extension and index conventions.
        """
        return [base]

    def workspace_packages(self, project_root: Path) -> dict[str, str]:
        """``{package name: repository-relative source dir}`` for bare specifiers that are in-repo."""
        return {}
