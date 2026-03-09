"""Personal path detection using regex patterns.

This module detects personal filesystem paths that should not be committed
to version control. Common examples include:
- Windows user directories (C:\\Users\\jsmith\\)
- Unix home directories (/home/jsmith/)
- Cloud storage paths (/Dropbox/projects/)
- Dated project folders (/260124 DOCSTAR/)
"""

import re
from pathlib import Path

from .models import PathFinding


# Personal path patterns - compile once at module load
# Each pattern is designed to catch personal paths while excluding
# generic/test paths used in examples and CI environments.
PATTERNS: dict[str, re.Pattern[str]] = {
    # Pattern 1: Windows User Paths
    # Catches: C:\Users\jsmith\, c:/Users/alice/
    # Excludes: test, user, example, runner (CI/generic users)
    "windows_user": re.compile(
        r"[Cc]:[\\\/]Users[\\\/](?!test[\\\/]|user[\\\/]|example[\\\/]|runner[\\\/])[a-zA-Z0-9._-]+[\\\/]"
    ),
    # Pattern 2: Unix/Mac Home Directories
    # Catches: /home/jsmith/, /Users/alice/
    # Excludes: test, user, example, runner, ubuntu
    "unix_home": re.compile(
        r"/(?:Users|home)/(?!test/|user/|example/|runner/|ubuntu/)[a-zA-Z0-9._-]+/"
    ),
    # Pattern 3: Cloud Storage Paths
    # Catches: /Dropbox/projects/, \OneDrive\Documents\
    # Case-insensitive
    "cloud_storage": re.compile(
        r"[\\\/](?:Dropbox|OneDrive|Google\s*Drive|iCloud|Box|pCloud)[\\\/][^\\\/]+[\\\/]",
        re.IGNORECASE,
    ),
    # Pattern 4: Dated Project Folders
    # Catches: /251007 FIXTHEDOCS/, \260124 DOCSTAR\
    # Format: 6 digits + space + UPPERCASE
    "dated_folder": re.compile(r"[\\\/]\d{6}\s+[A-Z]+[\\\/]"),
    # Pattern 5: Common Personal Folders
    # Catches: /Documents/work/, /Desktop/project/
    # Case-insensitive
    "personal_folder": re.compile(
        r"[\\\/](?:Documents|Desktop|Downloads|Pictures|Videos)[\\\/][^\\\/]+[\\\/]",
        re.IGNORECASE,
    ),
    # Pattern 6: "My X" Folder Patterns
    # Catches: /My Projects/, \My Documents\
    # Case-insensitive
    "my_folder": re.compile(r"[\\\/]My\s+[A-Za-z0-9]+[\\\/]", re.IGNORECASE),
}

# Human-readable descriptions for each pattern
PATTERN_DESCRIPTIONS: dict[str, str] = {
    "windows_user": "Windows user directory (C:\\Users\\username\\)",
    "unix_home": "Unix/Mac home directory (/home/username/ or /Users/username/)",
    "cloud_storage": "Cloud storage path (Dropbox, OneDrive, Google Drive, iCloud, Box, pCloud)",
    "dated_folder": "Dated project folder (e.g., /260124 DOCSTAR/)",
    "personal_folder": "Personal folder (Documents, Desktop, Downloads, Pictures, Videos)",
    "my_folder": '"My X" folder pattern (My Projects, My Documents, etc.)',
}


def check_file_for_paths(file_path: Path) -> list[PathFinding]:
    """Check a single file for personal path patterns.

    Args:
        file_path: Path to the file to check

    Returns:
        List of PathFinding objects for each match found (empty if file cannot be read)
    """
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        # Skip files that can't be read
        return []

    return _scan_content(content, file_path)


def _scan_content(content: str, file_path: Path) -> list[PathFinding]:
    """Scan text content for personal path patterns.

    Args:
        content: The text content to scan
        file_path: The path to the file (for reporting)

    Returns:
        List of PathFinding objects for each match found
    """
    findings: list[PathFinding] = []
    lines = content.split("\n")

    for line_num, line in enumerate(lines, start=1):
        for pattern_name, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                findings.append(
                    PathFinding(
                        file=file_path,
                        line_number=line_num,
                        line_content=line.strip(),
                        pattern_name=pattern_name,
                        match=match.group(),
                    )
                )

    return findings


def get_pattern_descriptions() -> dict[str, str]:
    """Return human-readable descriptions of all patterns.

    Returns:
        Dictionary mapping pattern names to descriptions
    """
    return PATTERN_DESCRIPTIONS.copy()


def self_test() -> tuple[bool, list[PathFinding]]:
    """Verify this module itself doesn't contain real personal paths.

    Runs all patterns against the paths.py source code to ensure
    no personal paths have been accidentally committed.

    Returns:
        Tuple of (passed: bool, findings: list[PathFinding])
        passed is True if no personal paths found
    """
    # Read our own source file
    this_file = Path(__file__)
    findings = check_file_for_paths(this_file)

    # Filter out matches that are in comments, docstrings, or pattern descriptions
    # (these are documentation examples, not real personal paths)
    real_findings: list[PathFinding] = []
    for finding in findings:
        line = finding.line_content
        # Skip if line is a comment
        if line.strip().startswith("#"):
            continue
        # Skip docstring examples (lines with - at start, describing patterns)
        if line.strip().startswith("-"):
            continue
        # Skip lines that are clearly documentation/examples
        if "Catches:" in line or "Excludes:" in line or "e.g.," in line:
            continue
        if "example" in line.lower():
            continue
        # Skip pattern description strings (they contain example paths)
        if 'home/username' in line or 'Users/username' in line:
            continue
        if '"unix_home":' in line or '"windows_user":' in line:
            continue
        real_findings.append(finding)

    return len(real_findings) == 0, real_findings
