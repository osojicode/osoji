"""File filtering for safety checks."""

from pathlib import Path

from ..config import SHADOW_DIR


# Extensions that should be checked for safety issues
CHECKABLE_EXTENSIONS: set[str] = {
    # Python
    ".py",
    ".pyi",
    # JavaScript/TypeScript
    ".js",
    ".ts",
    ".mjs",
    ".jsx",
    ".tsx",
    # Config
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    # Docs
    ".md",
    ".txt",
    ".rst",
    # Shell
    ".sh",
    ".bash",
    ".zsh",
    # Environment (important for secrets!)
    ".env",
    ".env.example",
    ".env.local",
    ".env.development",
    ".env.production",
    # Database
    ".sql",
    # Markup
    ".xml",
    ".html",
    ".htm",
}

# Binary/generated extensions to skip (don't even try to read)
BINARY_EXTENSIONS: set[str] = {
    # Images
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".bmp",
    ".tiff",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".rar",
    ".7z",
    ".xz",
    # Executables
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    # Media
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".flac",
    ".mkv",
    # Fonts
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # Python compiled
    ".pyc",
    ".pyo",
    ".egg",
    ".whl",
    # Data
    ".db",
    ".sqlite",
    ".sqlite3",
    # Lock files
    ".lock",
}

# Directories to skip entirely
SKIP_DIRECTORIES: set[str] = {
    # Version control
    ".git",
    ".hg",
    ".svn",
    # Python
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    # Virtual environments
    "venv",
    ".venv",
    "env",
    ".env",
    # Node
    "node_modules",
    ".npm",
    # Build outputs
    "build",
    "dist",
    "target",
    # Coverage
    "coverage",
    "htmlcov",
    ".coverage",
    # IDE
    ".idea",
    ".vscode",
    # Docstar own output
    SHADOW_DIR,
}


def should_check_file(file_path: Path) -> bool:
    """Determine if a file should be safety-checked.

    Args:
        file_path: Path to the file

    Returns:
        True if the file should be checked
    """
    # Skip the safety module's own test infrastructure.
    # These files intentionally contain example personal paths to test detection.
    # The test suite is the inverted check: the commit should be blocked if the
    # detector FAILS to find them, not if it succeeds.  pytest provides that
    # guarantee, so we skip them here to avoid circular blocking.
    parts_lower = [p.lower() for p in file_path.parts]
    if "safety" in parts_lower:
        name_lower = file_path.name.lower()
        if name_lower == "paths.py" or name_lower.startswith("test_"):
            return False

    # Skip binary extensions
    suffix_lower = file_path.suffix.lower()
    if suffix_lower in BINARY_EXTENSIONS:
        return False

    # Special handling for .env files (the "." is part of the name, not extension)
    # These are important to check for secrets!
    # Must check this BEFORE skip directories since ".env" is in SKIP_DIRECTORIES
    # as a directory (virtual env) but we want to check .env files
    file_name = file_path.name.lower()
    if file_name.startswith(".env"):
        return True

    # Check if it's in a skipped directory
    # Note: We only check parent directories, not the file itself
    for part in file_path.parts[:-1] if len(file_path.parts) > 1 else []:
        if part in SKIP_DIRECTORIES:
            return False
        # Handle glob patterns like *.egg-info
        for pattern in SKIP_DIRECTORIES:
            if "*" in pattern:
                import fnmatch

                if fnmatch.fnmatch(part, pattern):
                    return False

    # Check if extension is checkable
    # If no extension, check by default (could be a script like Makefile)
    if not file_path.suffix:
        return True

    return suffix_lower in CHECKABLE_EXTENSIONS


def filter_checkable_files(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """Filter a list of files into checkable and skipped.

    Args:
        files: List of file paths

    Returns:
        Tuple of (checkable_files, skipped_files)
    """
    checkable: list[Path] = []
    skipped: list[Path] = []

    for file_path in files:
        if should_check_file(file_path):
            checkable.append(file_path)
        else:
            skipped.append(file_path)

    return checkable, skipped
