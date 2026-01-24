"""File discovery with ignore patterns and bottom-up sorting."""

import fnmatch
from pathlib import Path

from .config import Config


def should_ignore(path: Path, ignore_patterns: set[str]) -> bool:
    """Check if a path should be ignored based on patterns."""
    name = path.name
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def discover_files(config: Config) -> list[Path]:
    """Discover all source files to process.

    Returns files sorted by depth (deepest first) for bottom-up processing.
    """
    files: list[Path] = []

    for path in config.root_path.rglob("*"):
        # Skip if any parent directory should be ignored
        skip = False
        for parent in path.relative_to(config.root_path).parents:
            if parent != Path(".") and should_ignore(config.root_path / parent, config.ignore_patterns):
                skip = True
                break

        if skip:
            continue

        # Skip ignored files/directories
        if should_ignore(path, config.ignore_patterns):
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
