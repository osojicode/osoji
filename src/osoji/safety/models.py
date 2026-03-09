"""Data models for safety check results."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PathFinding:
    """A personal path was detected in a file."""

    file: Path
    line_number: int
    line_content: str
    pattern_name: str
    match: str


@dataclass
class SecretFinding:
    """A potential secret was detected in a file."""

    file: Path
    line_number: int
    secret_type: str  # e.g., "AWS Access Key", "Private Key"


@dataclass
class CheckResult:
    """Combined result of all safety checks on one or more files."""

    path_findings: list[PathFinding] = field(default_factory=list)
    secret_findings: list[SecretFinding] = field(default_factory=list)
    files_checked: int = 0
    files_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return True if no findings of any kind."""
        return not self.path_findings and not self.secret_findings

    @property
    def finding_count(self) -> int:
        """Total number of findings."""
        return len(self.path_findings) + len(self.secret_findings)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        if self.passed:
            return f"Safety check passed - {self.files_checked} file(s) checked"
        return (
            f"Safety check FAILED - {self.finding_count} issue(s) "
            f"in {self.files_checked} file(s)"
        )

    def merge(self, other: "CheckResult") -> "CheckResult":
        """Merge another CheckResult into a new combined result."""
        return CheckResult(
            path_findings=self.path_findings + other.path_findings,
            secret_findings=self.secret_findings + other.secret_findings,
            files_checked=self.files_checked + other.files_checked,
            files_skipped=self.files_skipped + other.files_skipped,
            errors=self.errors + other.errors,
        )
