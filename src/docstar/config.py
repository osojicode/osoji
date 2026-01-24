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
}

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

    @property
    def shadow_root(self) -> Path:
        """Return the root directory for shadow docs."""
        return self.root_path / SHADOW_DIR / SHADOW_SUBDIR

    def shadow_path_for(self, source_path: Path) -> Path:
        """Return the shadow doc path for a given source file."""
        relative = source_path.relative_to(self.root_path)
        return self.shadow_root / (str(relative) + ".shadow.md")

    def shadow_path_for_dir(self, dir_path: Path) -> Path:
        """Return the shadow doc path for a directory roll-up."""
        relative = dir_path.relative_to(self.root_path)
        if relative == Path("."):
            return self.shadow_root / "_root.shadow.md"
        return self.shadow_root / relative / "_directory.shadow.md"
