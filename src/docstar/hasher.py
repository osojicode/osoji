"""Hashing and line number preprocessing utilities."""

import hashlib
from pathlib import Path


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of content, returning first 16 hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def compute_file_hash(path: Path) -> str:
    """Compute hash of a file's contents."""
    content = path.read_text(encoding="utf-8")
    return compute_hash(content)


def add_line_numbers(content: str) -> str:
    """Prepend line numbers to each line of content.

    Format: "   1 | line content"
    Line numbers are right-aligned to 4 characters.
    """
    lines = content.splitlines()
    width = max(4, len(str(len(lines))))
    numbered_lines = [f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1)]
    return "\n".join(numbered_lines)


def extract_source_hash(shadow_content: str) -> str | None:
    """Extract the source hash from a shadow doc's header.

    Looks for a line like: @source-hash: abc123...
    Returns None if not found.
    """
    for line in shadow_content.splitlines()[:10]:  # Check first 10 lines
        if line.startswith("@source-hash:"):
            return line.split(":", 1)[1].strip()
    return None
