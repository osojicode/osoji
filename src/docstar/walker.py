"""File discovery with ignore patterns and bottom-up sorting."""

import fnmatch
import subprocess
from collections.abc import Iterable
from pathlib import Path

from .config import Config
from .hooks import find_git_root


def should_ignore(path: Path, ignore_patterns: set[str]) -> bool:
    """Check if a path should be ignored based on patterns."""
    name = path.name
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _matches_ignore(path: Path, patterns: list[str] | set[str]) -> bool:
    """Check if a relative path matches any ignore pattern.

    Checks both the full path string and each individual path component,
    mirroring the logic in debris.py.
    """
    path_str = str(path)
    for pattern in patterns:
        if fnmatch.fnmatch(path_str, pattern):
            return True
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _git_ls_files(root: Path) -> set[Path] | None:
    """List files known to git, respecting .gitignore.

    Returns a set of absolute Paths, or None if git is unavailable
    or the directory is not inside a git repository.
    """
    git_root = find_git_root(root)
    if git_root is None:
        return None

    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            paths.add((root / line).resolve())
    return paths


def list_repo_files(config: Config) -> tuple[Iterable[Path], bool]:
    """Shared entry point for git-aware file listing.

    Returns (paths, used_git) where used_git indicates whether
    git ls-files was used (True) or rglob fallback (False).
    """
    if config.respect_gitignore:
        git_files = _git_ls_files(config.root_path)
        if git_files is not None:
            return git_files, True

    return config.root_path.rglob("*"), False


def discover_files(config: Config) -> list[Path]:
    """Discover all source files to process.

    Returns files sorted by depth (deepest first) for bottom-up processing.
    Applies both DEFAULT_IGNORE_PATTERNS and .docstarignore patterns.
    Uses git ls-files when available to respect .gitignore.
    """
    docstarignore = config.load_docstarignore()
    files: list[Path] = []

    all_paths, used_git = list_repo_files(config)

    for path in all_paths:
        # Ensure absolute path for git results
        if not path.is_absolute():
            path = config.root_path / path

        relative = path.relative_to(config.root_path)

        if not used_git:
            # rglob fallback: check parent directories for ignore patterns
            skip = False
            for parent in relative.parents:
                if parent != Path(".") and should_ignore(config.root_path / parent, config.ignore_patterns):
                    skip = True
                    break
            if skip:
                continue

        # Always apply ignore patterns as belt-and-suspenders
        if should_ignore(path, config.ignore_patterns):
            continue

        # Skip .docstarignore patterns
        if docstarignore and _matches_ignore(relative, docstarignore):
            continue

        # Only include files with matching extensions
        if path.is_file() and path.suffix in config.extensions:
            files.append(path)

    # Sort by depth (deepest first), then alphabetically
    files.sort(key=lambda p: (-len(p.parts), str(p)))

    return files


def discover_directories(config: Config, files: list[Path]) -> list[Path]:
    """Discover directories that contain processed files.

    Returns directories sorted by depth (deepest first) for bottom-up processing.
    """
    dirs: set[Path] = set()

    for file_path in files:
        # Add all parent directories up to (but not including) root
        current = file_path.parent
        while current != config.root_path:
            dirs.add(current)
            current = current.parent

    # Add root directory itself
    dirs.add(config.root_path)

    # Sort by depth (deepest first), then alphabetically
    dir_list = sorted(dirs, key=lambda p: (-len(p.parts), str(p)))

    return dir_list


def get_direct_children(config: Config, dir_path: Path, all_files: list[Path]) -> list[Path]:
    """Get files that are direct children of a directory."""
    return [f for f in all_files if f.parent == dir_path]


def get_child_directories(dir_path: Path, all_dirs: list[Path]) -> list[Path]:
    """Get directories that are direct children of a directory."""
    return [d for d in all_dirs if d.parent == dir_path]
