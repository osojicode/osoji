"""File discovery with ignore patterns and bottom-up sorting."""

import fnmatch
import subprocess
from collections.abc import Iterable
from pathlib import Path

from .config import Config, SHADOW_DIR
from .hooks import find_git_root

# Module-level cache: root_path → (file list, used_git flag)
_repo_files_cache: dict[Path, tuple[list[Path], bool]] = {}


def clear_repo_files_cache() -> None:
    """Clear the cached git ls-files results. Call between tests for isolation."""
    _repo_files_cache.clear()


def _matches_ignore(path: Path, patterns: list[str] | set[str]) -> str | None:
    """Check if a relative path matches any ignore pattern.

    Checks both the full path string and each individual path component.
    For multi-segment patterns (containing '/'), also checks if the
    normalized path starts with the pattern as a directory prefix.
    Returns the matched pattern name, or None if no match.
    """
    path_str = str(path)
    for pattern in patterns:
        if fnmatch.fnmatch(path_str, pattern):
            return pattern
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return pattern
        # Multi-segment patterns: treat as directory prefix
        if "/" in pattern:
            normalized = path_str.replace("\\", "/")
            if normalized.startswith(pattern + "/") or normalized == pattern:
                return pattern
    return None


def _git_ls_files(root: Path) -> list[Path] | None:
    """List files known to git, respecting .gitignore.

    Returns a list of absolute Paths, or None if git is unavailable
    or the directory is not inside a git repository. Excludes .osoji/
    paths since those are osoji's own output.
    """
    git_root = find_git_root(root)
    if git_root is None:
        return None

    print("  Running git ls-files...", flush=True)
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

    paths: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith(SHADOW_DIR + "/"):
            # Use simple path join — root is already resolved
            paths.append(root / line)
    print(f"  Git returned {len(paths)} files", flush=True)
    return paths


def list_repo_files(config: Config) -> tuple[Iterable[Path], bool]:
    """Shared entry point for git-aware file listing.

    Returns (paths, used_git) where used_git indicates whether
    git ls-files was used (True) or rglob fallback (False).
    Results are cached per root_path so git ls-files only runs once.
    """
    key = config.root_path

    if key in _repo_files_cache:
        cached_paths, used_git = _repo_files_cache[key]
        return list(cached_paths), used_git

    if config.respect_gitignore:
        git_files = _git_ls_files(config.root_path)
        if git_files is not None:
            _repo_files_cache[key] = (git_files, True)
            return list(git_files), True

    fallback = list(config.root_path.rglob("*"))
    _repo_files_cache[key] = (fallback, False)
    return list(fallback), False


def discover_files(config: Config) -> list[Path]:
    """Discover all source files to process.

    Returns files sorted by depth (deepest first) for bottom-up processing.
    Applies both DEFAULT_IGNORE_PATTERNS and .osojiignore patterns.
    Uses git ls-files when available to respect .gitignore.
    """
    from collections import Counter

    osojiignore = config.load_osojiignore()
    files: list[Path] = []

    all_paths, used_git = list_repo_files(config)
    # Materialize for progress counting
    all_paths = list(all_paths)
    total = len(all_paths)

    # Track files skipped by ignore patterns (for advisory warning)
    ignored_by_pattern: Counter[str] = Counter()

    for i, path in enumerate(all_paths):
        # Ensure absolute path for git results
        if not path.is_absolute():
            path = config.root_path / path

        relative = path.relative_to(config.root_path)

        # Skip .osoji directory early (our own output)
        if str(relative).startswith(SHADOW_DIR):
            continue

        # Check extension before expensive is_file() stat call
        if path.suffix not in config.extensions:
            continue

        # Check all path components against ignore patterns
        # (catches .cargo, node_modules, vendor etc. even when committed to git)
        matched_pattern = _matches_ignore(relative, config.ignore_patterns)
        if matched_pattern:
            if used_git:
                ignored_by_pattern[matched_pattern] += 1
            continue

        # Skip .osojiignore patterns
        if osojiignore and _matches_ignore(relative, osojiignore):
            continue

        # Only include actual files
        # Skip stat call when git provided the file list (git only returns files)
        if used_git or path.is_file():
            files.append(path)

        # Progress every 100 paths or at the end
        if (i + 1) % 100 == 0 or i + 1 == total:
            print(f"\r  Scanned {i + 1}/{total} paths ({len(files)} source files)\033[K", end="", flush=True)

    if total > 0:
        print()  # newline after progress

    # Warn about git-tracked files matching default ignore patterns
    if ignored_by_pattern:
        total_ignored = sum(ignored_by_pattern.values())
        pattern_summary = ", ".join(
            f"{pat} ({count})" for pat, count in ignored_by_pattern.most_common(5)
        )
        print(f"  Warning: {total_ignored} git-tracked file(s) matched default ignore patterns: {pattern_summary}", flush=True)
        print(f"  These may be accidentally committed build artifacts.", flush=True)
        print(f"  To document them anyway, add negation patterns to .osojiignore (e.g. !registry)", flush=True)

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


def get_direct_children(dir_path: Path, all_files: list[Path]) -> list[Path]:
    """Get files that are direct children of a directory."""
    return [f for f in all_files if f.parent == dir_path]


def get_child_directories(dir_path: Path, all_dirs: list[Path]) -> list[Path]:
    """Get directories that are direct children of a directory."""
    return [d for d in all_dirs if d.parent == dir_path]
