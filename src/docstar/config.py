"""Configuration for Docstar."""

from dataclasses import dataclass, field
from pathlib import Path


# Directories to ignore during traversal
DEFAULT_IGNORE_PATTERNS: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "build",
    "dist",
    ".docstar",
    ".idea",
    ".vscode",
    ".github",
    # Build output
    "target",
    # Cargo / Rust ecosystem
    ".cargo",
    "toolchains",
    "registry",
    # Vendored dependencies (Go, PHP, Ruby)
    "vendor",
    # Rustup home
    ".rustup",
    # Gradle cache
    ".gradle",
    # Next.js / Nuxt.js / Turborepo / Parcel
    ".next",
    ".nuxt",
    ".turbo",
    ".parcel-cache",
    # Generic caches / temp / logs
    ".cache",
    "tmp",
    "temp",
    "logs",
    # Test coverage
    "coverage",
    ".nyc_output",
    # Legacy package managers
    "bower_components",
}

# Documentation file detection settings
DOC_EXTENSIONS: set[str] = {".md", ".markdown", ".rst", ".txt"}
DOC_FILENAMES: set[str] = {"README", "CHANGELOG", "CONTRIBUTING", "LICENSE", "AUTHORS"}
DOC_DIRECTORIES: set[str] = {"docs", "documentation", "doc"}

# File extensions to process
DEFAULT_EXTENSIONS: set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".clj",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".ml",
    ".mli",
    ".lua",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".r",
    ".R",
    ".sql",
    ".vue",
    ".svelte",
}

# Shadow doc output directory name
SHADOW_DIR = ".docstar"
SHADOW_SUBDIR = "shadow"

# LLM model to use
DEFAULT_MODEL = "claude-sonnet-4-20250514"


@dataclass
class Config:
    """Configuration for shadow doc generation."""

    root_path: Path
    ignore_patterns: set[str] = field(default_factory=lambda: DEFAULT_IGNORE_PATTERNS.copy())
    extensions: set[str] = field(default_factory=lambda: DEFAULT_EXTENSIONS.copy())
    model: str = DEFAULT_MODEL
    force: bool = False
    max_concurrency: int = 100
    respect_gitignore: bool = True

    # Documentation detection (for debris scanning)
    doc_extensions: set[str] = field(default_factory=lambda: DOC_EXTENSIONS.copy())
    doc_filenames: set[str] = field(default_factory=lambda: DOC_FILENAMES.copy())
    doc_directories: set[str] = field(default_factory=lambda: DOC_DIRECTORIES.copy())

    @property
    def shadow_root(self) -> Path:
        """Return the root directory for shadow docs."""
        return self.root_path / SHADOW_DIR / SHADOW_SUBDIR

    def shadow_path_for(self, source_path: Path) -> Path:
        """Return the shadow doc path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.shadow_root / (str(relative) + ".shadow.md")

    def findings_path_for(self, source_path: Path) -> Path:
        """Return the findings JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.root_path / SHADOW_DIR / "findings" / (str(relative) + ".findings.json")

    def shadow_path_for_dir(self, dir_path: Path) -> Path:
        """Return the shadow doc path for a directory roll-up."""
        relative = dir_path.relative_to(self.root_path)
        if relative == Path("."):
            return self.shadow_root / "_root.shadow.md"
        return self.shadow_root / relative / "_directory.shadow.md"

    @property
    def rules_path(self) -> Path:
        """Path to natural language rules file."""
        return self.root_path / ".docstar" / "rules"

    @property
    def ignore_path(self) -> Path:
        """Path to .docstarignore file."""
        return self.root_path / ".docstarignore"

    def load_rules_text(self) -> str:
        """Load raw rules text from .docstar/rules.

        Returns empty string if file doesn't exist.
        LLM interprets the natural language directly.
        """
        if not self.rules_path.exists():
            return ""
        return self.rules_path.read_text(encoding="utf-8")

    def load_docstarignore(self) -> list[str]:
        """Load patterns from .docstarignore (fnmatch patterns on paths).

        Supports negation: lines starting with ! remove that pattern
        from the default ignore_patterns. E.g. "!registry" would
        stop ignoring directories named "registry".
        """
        if not self.ignore_path.exists():
            return []
        content = self.ignore_path.read_text(encoding="utf-8")
        extra_patterns: list[str] = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                # Negation: remove from default ignore patterns
                negated = line[1:]
                self.ignore_patterns.discard(negated)
            else:
                extra_patterns.append(line)
        return extra_patterns

    def is_doc_candidate(self, path: Path) -> bool:
        """Check if a path is a documentation file candidate.

        Matches based on:
        - Extension (.md, .markdown, .rst, .txt)
        - Filename (README, CHANGELOG, etc. regardless of extension)
        - Location (files in docs/ directory)
        """
        # Check extension
        if path.suffix.lower() in self.doc_extensions:
            return True

        # Check filename (without extension)
        if path.stem.upper() in {f.upper() for f in self.doc_filenames}:
            return True

        # Check if in a doc directory
        try:
            for parent in path.relative_to(self.root_path).parents:
                if parent.name.lower() in {d.lower() for d in self.doc_directories}:
                    return True
        except ValueError:
            pass  # Path not relative to root_path

        return False
