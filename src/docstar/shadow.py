"""Core shadow documentation generation orchestration."""

from datetime import datetime, timezone
from pathlib import Path

import anthropic

from .config import Config
from .hasher import add_line_numbers, compute_file_hash, extract_source_hash
from .llm import generate_file_shadow_doc, generate_directory_shadow_doc, get_client
from .walker import (
    discover_files,
    discover_directories,
    get_direct_children,
    get_child_directories,
)


def assemble_shadow_doc(file_path: Path, source_hash: str, body: str) -> str:
    """Assemble a complete shadow doc with header."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"# {file_path}\n@source-hash: {source_hash}\n@generated: {timestamp}\n\n"
    return header + body


def assemble_directory_shadow_doc(dir_path: Path, body: str) -> str:
    """Assemble a complete directory shadow doc with header."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"# {dir_path}/\n@generated: {timestamp}\n\n"
    return header + body


def is_stale(config: Config, source_path: Path) -> bool:
    """Check if a shadow doc needs regeneration.

    Returns True if:
    - Shadow doc doesn't exist
    - Source hash doesn't match
    - Force flag is set
    """
    if config.force:
        return True

    shadow_path = config.shadow_path_for(source_path)
    if not shadow_path.exists():
        return True

    try:
        shadow_content = shadow_path.read_text(encoding="utf-8")
        cached_hash = extract_source_hash(shadow_content)
        if cached_hash is None:
            return True

        current_hash = compute_file_hash(source_path)
        return cached_hash != current_hash
    except Exception:
        return True


def process_file(
    client: anthropic.Anthropic,
    config: Config,
    file_path: Path,
) -> tuple[Path, str]:
    """Process a single file and generate/retrieve its shadow doc.

    Returns (file_path, shadow_doc_body) for use in directory roll-ups.
    """
    shadow_path = config.shadow_path_for(file_path)
    relative_path = file_path.relative_to(config.root_path)

    # Check if we can use cached version
    if not is_stale(config, file_path):
        # Read existing shadow doc and extract body (skip header)
        shadow_content = shadow_path.read_text(encoding="utf-8")
        lines = shadow_content.split("\n")
        # Find where body starts (after blank line following header)
        body_start = 0
        for i, line in enumerate(lines):
            if line == "" and i > 0:
                body_start = i + 1
                break
        body = "\n".join(lines[body_start:])
        print(f"  [cached] {relative_path}")
        return (file_path, body)

    # Generate new shadow doc
    print(f"  [generating] {relative_path}")

    content = file_path.read_text(encoding="utf-8")
    numbered_content = add_line_numbers(content)
    source_hash = compute_file_hash(file_path)

    body = generate_file_shadow_doc(client, config, file_path, numbered_content)
    full_doc = assemble_shadow_doc(relative_path, source_hash, body)

    # Write shadow doc
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_path.write_text(full_doc, encoding="utf-8")

    return (file_path, body)


def process_directory(
    client: anthropic.Anthropic,
    config: Config,
    dir_path: Path,
    file_bodies: dict[Path, str],
    dir_bodies: dict[Path, str],
    all_files: list[Path],
    all_dirs: list[Path],
) -> str:
    """Process a directory and generate its roll-up shadow doc.

    Returns the shadow doc body for use in parent directory roll-ups.
    """
    relative_path = dir_path.relative_to(config.root_path)
    if relative_path == Path("."):
        relative_path = Path("(root)")

    print(f"  [rolling up] {relative_path}/")

    # Gather summaries from direct children
    child_summaries: list[tuple[Path, str]] = []

    # Add file children
    for file_path in get_direct_children(config, dir_path, all_files):
        if file_path in file_bodies:
            child_summaries.append((file_path, file_bodies[file_path]))

    # Add directory children
    for child_dir in get_child_directories(dir_path, all_dirs):
        if child_dir in dir_bodies:
            child_summaries.append((child_dir, dir_bodies[child_dir]))

    if not child_summaries:
        return ""

    body = generate_directory_shadow_doc(client, config, dir_path, child_summaries)
    full_doc = assemble_directory_shadow_doc(relative_path, body)

    # Write shadow doc
    shadow_path = config.shadow_path_for_dir(dir_path)
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_path.write_text(full_doc, encoding="utf-8")

    return body


def generate_shadow_docs(config: Config) -> None:
    """Generate shadow documentation for an entire codebase."""
    print(f"Generating shadow documentation for: {config.root_path}")

    # Discover files and directories
    files = discover_files(config)
    dirs = discover_directories(config, files)

    if not files:
        print("No source files found to process.")
        return

    print(f"Found {len(files)} source files in {len(dirs)} directories")

    # Create client
    client = get_client()

    # Process files (bottom-up, deepest first)
    print("\nProcessing files:")
    file_bodies: dict[Path, str] = {}
    for file_path in files:
        path, body = process_file(client, config, file_path)
        file_bodies[path] = body

    # Process directories (bottom-up, deepest first)
    print("\nRolling up directories:")
    dir_bodies: dict[Path, str] = {}
    for dir_path in dirs:
        body = process_directory(
            client, config, dir_path, file_bodies, dir_bodies, files, dirs
        )
        dir_bodies[dir_path] = body

    print(f"\nShadow documentation written to: {config.shadow_root}")


def check_shadow_docs(config: Config) -> list[tuple[Path, str]]:
    """Check for stale or missing shadow docs.

    Returns a list of (path, status) tuples where status is 'missing' or 'stale'.
    """
    files = discover_files(config)
    issues: list[tuple[Path, str]] = []

    for file_path in files:
        shadow_path = config.shadow_path_for(file_path)
        relative = file_path.relative_to(config.root_path)

        if not shadow_path.exists():
            issues.append((relative, "missing"))
        elif is_stale(config, file_path):
            issues.append((relative, "stale"))

    return issues
