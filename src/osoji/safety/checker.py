"""Orchestrator for safety checks - combines path and secret detection."""

from pathlib import Path

from .filters import filter_checkable_files, should_check_file
from .models import CheckResult, PathFinding, SecretFinding
from .paths import check_file_for_paths
from .secrets import check_file_for_secrets, is_available as secrets_available


def check_file(file_path: Path) -> CheckResult:
    """Run all safety checks on a single file.

    Args:
        file_path: Path to the file to check

    Returns:
        CheckResult with any findings
    """
    result = CheckResult(files_checked=1)

    if not should_check_file(file_path):
        result.files_checked = 0
        result.files_skipped = 1
        return result

    if not file_path.exists():
        result.files_checked = 0
        result.errors.append(f"File not found: {file_path}")
        return result

    try:
        # Check for personal paths
        path_findings = check_file_for_paths(file_path)
        result.path_findings.extend(path_findings)

        # Check for secrets (if detect-secrets available)
        secret_findings = check_file_for_secrets(file_path)
        result.secret_findings.extend(secret_findings)

    except Exception as e:
        result.errors.append(f"{file_path}: {e}")

    return result


def check_files(file_paths: list[Path]) -> CheckResult:
    """Run safety checks on multiple files.

    Args:
        file_paths: List of file paths to check

    Returns:
        Combined CheckResult for all files
    """
    checkable, skipped = filter_checkable_files(file_paths)

    combined = CheckResult(files_skipped=len(skipped))

    for file_path in checkable:
        file_result = check_file(file_path)
        combined = combined.merge(file_result)

    return combined


def check_staged_files() -> CheckResult:
    """Check all staged files in a git repository.

    Returns:
        CheckResult for all staged files
    """
    # Import here to avoid circular imports
    from ..hooks import find_git_root, get_staged_files_all

    repo_path = Path.cwd()

    git_root = find_git_root(repo_path)
    if git_root is None:
        result = CheckResult()
        result.errors.append("Not a git repository")
        return result

    # Get all staged files (not filtered by extension)
    staged_files = get_staged_files_all(git_root)

    if not staged_files:
        return CheckResult()  # Nothing staged

    return check_files(staged_files)


def format_check_result(result: CheckResult, verbose: bool = False) -> str:
    """Format CheckResult as a human-readable report.

    Args:
        result: The CheckResult to format
        verbose: Include skipped file count and other details

    Returns:
        Formatted string report
    """
    lines: list[str] = []

    if result.passed:
        lines.append("Safety check passed - no issues found.")
        if verbose:
            lines.append(f"  Files checked: {result.files_checked}")
            lines.append(f"  Files skipped: {result.files_skipped}")
            if not secrets_available():
                lines.append(
                    "  Note: detect-secrets not installed (secrets check skipped)"
                )
        return "\n".join(lines)

    # Header
    lines.append("Safety check FAILED")
    lines.append("")

    # Personal path findings
    if result.path_findings:
        lines.append(f"## Personal Paths Found ({len(result.path_findings)})")
        lines.append("")

        # Group by file
        by_file: dict[Path, list[PathFinding]] = {}
        for finding in result.path_findings:
            by_file.setdefault(finding.file, []).append(finding)

        for file_path, findings in sorted(by_file.items()):
            lines.append(f"**{file_path}**")
            for f in findings:
                lines.append(f"  Line {f.line_number}: `{f.match}`")
                lines.append(f"    Pattern: {f.pattern_name}")
            lines.append("")

    # Secret findings
    if result.secret_findings:
        lines.append(f"## Potential Secrets Found ({len(result.secret_findings)})")
        lines.append("")

        by_file_secrets: dict[Path, list[SecretFinding]] = {}
        for finding in result.secret_findings:
            by_file_secrets.setdefault(finding.file, []).append(finding)

        for file_path, findings in sorted(by_file_secrets.items()):
            lines.append(f"**{file_path}**")
            for f in findings:
                lines.append(f"  Line {f.line_number}: {f.secret_type}")
            lines.append("")

    # Remediation suggestions
    lines.append("---")
    lines.append("")

    if result.path_findings:
        lines.append("Replace personal paths with generic alternatives:")
        lines.append("  - /path/to/project")
        lines.append("  - ~/workspace/project")
        lines.append("  - ./relative/path")
        lines.append("")

    if result.secret_findings:
        lines.append("Move secrets to environment variables.")
        lines.append("")

    lines.append("To bypass in emergencies: git commit --no-verify")

    # Summary
    lines.append("")
    lines.append("---")
    lines.append(
        f"Total: {result.finding_count} issue(s) in {result.files_checked} file(s)"
    )

    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for error in result.errors:
            lines.append(f"  - {error}")

    return "\n".join(lines)
