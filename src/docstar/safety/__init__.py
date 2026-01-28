"""Commit safety module - detect personal paths and secrets before commit.

This module provides pre-commit safety checks to prevent accidental commits
of personal filesystem paths and secrets. It's designed for future extraction
as a standalone package.

Usage:
    from docstar.safety import check_staged_files, CheckResult

    result = check_staged_files()
    if not result.passed:
        print(result.summary())

CLI:
    docstar safety check           # Check staged files
    docstar safety check file.py   # Check specific files
    docstar safety self-test       # Verify module is clean
    docstar safety patterns        # Show detection patterns
"""

from .checker import check_files, check_staged_files, format_check_result
from .models import CheckResult, PathFinding, SecretFinding

__all__ = [
    "check_staged_files",
    "check_files",
    "format_check_result",
    "CheckResult",
    "PathFinding",
    "SecretFinding",
]
