"""Plugin interface and shared types for language-specific AST extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractedFacts:
    """AST-extracted facts for a single file.

    string_literals is intentionally absent — the LLM always provides
    semantic string classification; AST tools cannot replicate that.
    """

    imports: list[dict[str, Any]] = field(default_factory=list)
    exports: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    member_writes: list[dict[str, Any]] = field(default_factory=list)

    def to_file_facts_dict(self, source: str, source_hash: str) -> dict:
        """Convert to a dict compatible with the facts JSON schema."""
        return {
            "source": source,
            "source_hash": source_hash,
            "imports": self.imports,
            "exports": self.exports,
            "calls": self.calls,
            "member_writes": self.member_writes,
            "extraction_method": "ast",
        }


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
