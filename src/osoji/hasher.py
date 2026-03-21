"""Hashing and line number preprocessing utilities."""

import hashlib
from functools import lru_cache
from pathlib import Path


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of content, returning first 16 hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def compute_file_hash(path: Path) -> str:
    """Compute hash of a file's contents.

    Uses read_file_safe() so binary/misencoded files get a raw-bytes hash
    instead of crashing.
    """
    content, is_binary = read_file_safe(path)
    if is_binary:
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:16]
    return compute_hash(content)


def read_file_safe(path: Path) -> tuple[str, bool]:
    """Read a file with robust encoding. Returns (content, is_binary).

    Binary detection (in order):
    1. Null bytes in first 8KB (catches most binary formats)
    2. UTF-8 validity — valid UTF-8 is treated as text (skips byte-ratio heuristic)
    3. Non-text byte ratio for non-UTF-8 files (>10% non-text = binary)
    """
    raw = path.read_bytes()[:8192]

    # Check 1: null bytes
    if b'\x00' in raw:
        return "", True

    # Check 2: valid UTF-8 → text (skip byte-ratio heuristic)
    # Real binary files (JPEG, etc.) are virtually never valid UTF-8, and the
    # null-byte check above already catches most binary formats. This prevents
    # false positives on UTF-8 files with multi-byte characters (e.g. box-drawing,
    # emoji, CJK) that have a high ratio of non-ASCII bytes.
    check_raw = raw[3:] if raw.startswith(b'\xef\xbb\xbf') else raw
    try:
        check_raw.decode("utf-8")  # strict — raises on any invalid sequence
        is_valid_utf8 = True
    except UnicodeDecodeError as e:
        # The 8KB slice may truncate a multi-byte sequence at the boundary.
        # If the only error is within the last 3 bytes, it's just truncation.
        is_valid_utf8 = e.start >= len(check_raw) - 3

    if is_valid_utf8:
        try:
            return path.read_text(encoding="utf-8-sig"), False
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace"), False

    # Check 3: non-text byte ratio (only reached for non-UTF-8 files)
    if check_raw:
        non_text = sum(1 for b in check_raw if b not in _TEXT_BYTES)
        if non_text / len(check_raw) > 0.10:  # >10% non-text = binary
            return "", True

    try:
        return path.read_text(encoding="utf-8-sig"), False
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace"), False


_TEXT_BYTES = frozenset(range(0x20, 0x7f)) | {0x09, 0x0a, 0x0d}


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


def compute_children_hash(child_entries: list[tuple[str, str]]) -> str:
    """Compute Merkle-style hash from sorted (name, content_hash) pairs.

    For files, content_hash is the source-hash. For dirs, it's their children-hash.
    Catches adds, removes, and content changes in a single comparison.
    """
    sorted_entries = sorted(child_entries)
    combined = "\n".join(f"{name}:{hash}" for name, hash in sorted_entries)
    return compute_hash(combined)


def extract_children_hash(shadow_content: str) -> str | None:
    """Extract the children hash from a directory shadow doc header."""
    for line in shadow_content.splitlines()[:10]:
        if line.startswith("@children-hash:"):
            return line.split(":", 1)[1].strip()
    return None


# --- Implementation hash ---
# Files that cannot affect shadow/audit output.
# Everything else under src/osoji/ IS included (blacklist approach).
_IMPL_HASH_EXCLUDES = frozenset({
    "__init__.py",           # version string only
    "cli.py",               # CLI argument parsing, not analysis logic
    "hooks.py",             # git hook management
    "observatory.py",       # output consumer, not producer
    "stats.py",             # token counting statistics
    "safety/__init__.py",   # pre-commit safety checks —
    "safety/checker.py",    #   entirely separate from
    "safety/filters.py",    #   shadow/audit pipeline
    "safety/models.py",
    "safety/paths.py",
    "safety/secrets.py",
})


@lru_cache(maxsize=1)
def compute_impl_hash() -> str:
    """Compute a composite hash over the implementation files that affect shadow output.

    Auto-discovers all *.py under src/osoji/, excluding files in
    _IMPL_HASH_EXCLUDES.  Each entry is "rel_path:file_hash" sorted
    alphabetically, so adding/renaming a file changes the hash.
    Cached for the lifetime of the process.
    """
    # Resolve package root: this file lives at src/osoji/hasher.py
    pkg_dir = Path(__file__).resolve().parent          # src/osoji/

    entries: list[str] = []
    for py_file in sorted(pkg_dir.rglob("*.py")):
        rel = py_file.relative_to(pkg_dir).as_posix()
        if rel in _IMPL_HASH_EXCLUDES:
            continue
        h = compute_file_hash(py_file)
        entries.append(f"{rel}:{h}")

    return compute_hash("\n".join(entries))


def is_findings_current(
    source_hash: str | None,
    impl_hash: str | None,
    source_path: Path,
) -> bool:
    """Check if a findings sidecar is current against source and implementation."""
    if source_hash is None or impl_hash is None:
        return False
    try:
        if compute_file_hash(source_path) != source_hash:
            return False
    except (OSError, ValueError):
        return False
    return compute_impl_hash() == impl_hash


def extract_impl_hash(shadow_content: str) -> str | None:
    """Extract the impl hash from a shadow doc header.

    Looks for a line like: @impl-hash: abc123...
    Returns None if not found (old-format doc).
    """
    for line in shadow_content.splitlines()[:10]:
        if line.startswith("@impl-hash:"):
            return line.split(":", 1)[1].strip()
    return None
