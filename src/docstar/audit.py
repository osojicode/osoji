"""Documentation audit orchestration."""

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .shadow import check_shadow_docs, generate_shadow_docs
from .debris import detect_debris


@dataclass
class AuditIssue:
    """A single audit finding."""

    path: Path
    severity: str  # "error" or "warning"
    category: str  # "debris", "stale_shadow", "missing_shadow"
    message: str
    remediation: str


@dataclass
class AuditResult:
    """Complete audit result."""

    issues: list[AuditIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    @property
    def passed(self) -> bool:
        return not self.has_errors


def run_audit(config: Config, fix_shadow: bool = True) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Docstar configuration
        fix_shadow: If True, auto-update stale shadow docs (Docstar owns them)
    """
    issues: list[AuditIssue] = []

    # 1. Check shadow docs (auto-fix if enabled)
    shadow_issues = check_shadow_docs(config)

    if fix_shadow and shadow_issues:
        print("Docstar: Auto-updating shadow documentation...")
        generate_shadow_docs(config)
        shadow_issues = []  # Cleared by regeneration

    for path, status in shadow_issues:
        issues.append(AuditIssue(
            path=path,
            severity="warning",  # Shadow issues are warnings (omission)
            category=f"{status}_shadow",
            message=f"Shadow documentation is {status}",
            remediation="Run 'docstar shadow .' to update",
        ))

    # 2. Detect debris (errors - commission, not omission)
    print("Docstar: Scanning for documentation debris...")
    debris_results = detect_debris(config)

    for item in debris_results:
        if item.is_debris:
            issues.append(AuditIssue(
                path=item.path,
                severity="error",  # Debris is an error (misleads)
                category="debris",
                message=f"Documentation debris: {item.reason}",
                remediation=item.remediation,
            ))

    return AuditResult(issues=issues)


def format_audit_report(result: AuditResult, verbose: bool = False) -> str:
    """Format audit result as agent-ready markdown report."""
    if result.passed and not result.has_warnings:
        return "# Docstar Audit Passed\n\nNo issues found."

    lines = []

    if result.passed:
        lines.append("# Docstar Audit Passed")
    else:
        lines.append("# Docstar Audit Failed")

    lines.append("")

    errors = [i for i in result.issues if i.severity == "error"]
    warnings = [i for i in result.issues if i.severity == "warning"]

    if errors:
        lines.append("## Errors (blocking)\n")
        for issue in errors:
            lines.append(f"### `{issue.path}`")
            lines.append(f"**Category**: {issue.category}")
            lines.append(f"**Issue**: {issue.message}")
            lines.append(f"**Remediation**: {issue.remediation}")
            lines.append("")

    if warnings:
        lines.append("## Warnings (non-blocking)\n")
        for issue in warnings:
            lines.append(f"- `{issue.path}`: {issue.message}")
        lines.append("")

    lines.append("---")
    lines.append(f"**Result**: {len(errors)} error(s), {len(warnings)} warning(s)")

    if errors:
        lines.append("")
        lines.append("To override findings, add rules to `.docstar/rules`")

    return "\n".join(lines)
