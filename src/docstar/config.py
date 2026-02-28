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
    # Lock files (large, machine-generated)
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
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
    # Metadata / config files
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cfg",
    ".ini",
}

# Shadow doc output directory name
SHADOW_DIR = ".docstar"
SHADOW_SUBDIR = "shadow"
DIRECTORY_SHADOW_FILENAME = "_directory.shadow.md"

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

    @property
    def token_cache_path(self) -> Path:
        """Return the path to the persistent token-count cache."""
        return self.root_path / SHADOW_DIR / "token-cache.json"

    def shadow_path_for(self, source_path: Path) -> Path:
        """Return the shadow doc path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.shadow_root / (str(relative) + ".shadow.md")

    def findings_path_for(self, source_path: Path) -> Path:
        """Return the findings JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.root_path / SHADOW_DIR / "findings" / (str(relative) + ".findings.json")

    def symbols_path_for(self, source_path: Path) -> Path:
        """Return the symbols JSON sidecar path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.root_path / SHADOW_DIR / "symbols" / (str(relative) + ".symbols.json")

    def facts_path_for(self, source_path: Path) -> Path:
        """Return the facts JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.root_path / SHADOW_DIR / "facts" / (str(relative) + ".facts.json")

    def shadow_path_for_dir(self, dir_path: Path) -> Path:
        """Return the shadow doc path for a directory roll-up."""
        relative = dir_path.relative_to(self.root_path)
        if relative == Path("."):
            return self.shadow_root / "_root.shadow.md"
        return self.shadow_root / relative / DIRECTORY_SHADOW_FILENAME

    @property
    def analysis_root(self) -> Path:
        """Return the root directory for analysis outputs."""
        return self.root_path / SHADOW_DIR / "analysis"

    def analysis_docs_path_for(self, doc_path: Path) -> Path:
        """Return the analysis JSON path for a given doc file."""
        relative = doc_path.relative_to(self.root_path) if doc_path.is_absolute() else doc_path
        return self.analysis_root / "docs" / (str(relative) + ".analysis.json")

    def analysis_deadcode_path_for(self, source_path: Path) -> Path:
        """Return the dead-code analysis JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path) if source_path.is_absolute() else source_path
        return self.analysis_root / "dead-code" / (str(relative) + ".deadcode.json")

    def analysis_plumbing_path_for(self, source_path: Path) -> Path:
        """Return the plumbing analysis JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path) if source_path.is_absolute() else source_path
        return self.analysis_root / "plumbing" / (str(relative) + ".plumbing.json")

    def analysis_junk_path_for(self, analyzer_name: str, source_path: Path) -> Path:
        """Return the junk analysis JSON path for a given source file and analyzer."""
        relative = source_path.relative_to(self.root_path) if source_path.is_absolute() else source_path
        return self.analysis_root / "junk" / analyzer_name / (str(relative) + f".{analyzer_name}.json")

    def signatures_path_for(self, source_path: Path) -> Path:
        """Return the signature JSON path for a given source file."""
        relative = source_path.relative_to(self.root_path) if source_path.is_absolute() else source_path
        return self.root_path / SHADOW_DIR / "signatures" / (str(relative) + ".signature.json")

    def signatures_path_for_dir(self, dir_path: Path) -> Path:
        """Return the signature JSON path for a directory."""
        relative = dir_path.relative_to(self.root_path) if dir_path.is_absolute() else dir_path
        if relative == Path("."):
            return self.root_path / SHADOW_DIR / "signatures" / "_directory.signature.json"
        return self.root_path / SHADOW_DIR / "signatures" / relative / "_directory.signature.json"

    @property
    def scorecard_path(self) -> Path:
        """Return the path to the scorecard JSON."""
        return self.analysis_root / "scorecard.json"

    @property
    def staleness_manifest_path(self) -> Path:
        """Return the path to the staleness manifest JSON."""
        return self.root_path / SHADOW_DIR / "staleness.json"

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
                negated = line[1:].strip("/")
                if negated:
                    self.ignore_patterns.discard(negated)
            else:
                normalized = line.strip("/")
                if normalized:
                    extra_patterns.append(normalized)
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
