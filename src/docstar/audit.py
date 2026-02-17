"""Documentation audit orchestration."""

import json
import time as time_module
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .shadow import check_shadow_docs, generate_shadow_docs
from .debris import detect_debris, validate_cross_references
from .walker import _matches_ignore


@dataclass
class AuditIssue:
    """A single audit finding."""

    path: Path
    severity: str  # "error" or "warning"
    category: str  # "debris", "stale_shadow", "missing_shadow"
    message: str
    remediation: str
    line_start: int | None = None
    line_end: int | None = None


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


def _make_progress_default(config: Config):
    """Create an inline progress bar callback (carriage return, same line)."""
    def progress(completed: int, total: int, path: Path, status: str) -> None:
        pct = completed / total * 100 if total > 0 else 0
        symbols = {
            "ok": "[ok]",
            "debris": "[DEBRIS]",
            "error": "[ERROR]",
            "skipped": "[skip]",
        }
        symbol = symbols.get(status, f"[{status}]")
        relative = path.relative_to(config.root_path) if path.is_absolute() else path
        print(f"\r  [{completed}/{total}] {pct:.0f}% {symbol} {relative.name}\033[K", end="", flush=True)
        if completed == total:
            print()
    return progress


def _make_progress_verbose(config: Config):
    """Create a verbose progress callback (one line per file)."""
    def progress(completed: int, total: int, path: Path, status: str) -> None:
        symbols = {
            "ok": "[ok]",
            "debris": "[DEBRIS]",
            "error": "[ERROR]",
            "skipped": "[skip]",
        }
        symbol = symbols.get(status, f"[{status}]")
        relative = path.relative_to(config.root_path) if path.is_absolute() else path
        print(f"  {symbol} {relative}", flush=True)
    return progress


def run_audit(
    config: Config,
    fix_shadow: bool = True,
    xref: bool = False,
    verbose: bool = False,
) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Docstar configuration
        fix_shadow: If True, auto-update stale shadow docs (Docstar owns them)
        xref: If True, run cross-reference validation (LLM calls per .md file)
        verbose: If True, show detailed per-file progress and timing
    """
    issues: list[AuditIssue] = []
    progress_cb = _make_progress_verbose(config) if verbose else _make_progress_default(config)
    docstarignore = config.load_docstarignore()

    # 1. Check shadow docs (auto-fix if enabled)
    print("Docstar: Checking shadow documentation...", flush=True)
    shadow_issues = check_shadow_docs(config)

    if fix_shadow and shadow_issues:
        print(f"Docstar: Auto-updating {len(shadow_issues)} shadow doc(s)...", flush=True)
        phase_start = time_module.monotonic()
        generate_shadow_docs(config, verbose=verbose)
        shadow_issues = []  # Cleared by regeneration
        if verbose:
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s]", flush=True)

    for path, status in shadow_issues:
        issues.append(AuditIssue(
            path=path,
            severity="warning",  # Shadow issues are warnings (omission)
            category=f"{status}_shadow",
            message=f"Shadow documentation is {status}",
            remediation="Run 'docstar shadow .' to update",
        ))

    # 2. Detect debris (errors - commission, not omission)
    print("Docstar: Scanning for documentation debris...", flush=True)
    phase_start = time_module.monotonic()
    debris_results = detect_debris(config, on_progress=progress_cb)
    if verbose:
        elapsed = time_module.monotonic() - phase_start
        print(f"  [{elapsed:.1f}s]", flush=True)

    for item in debris_results:
        if item.is_debris:
            issues.append(AuditIssue(
                path=item.path,
                severity="error",  # Debris is an error (misleads)
                category="debris",
                message=f"Documentation debris: {item.reason}",
                remediation=item.remediation,
            ))

    # 3. Surface code debris findings from shadow generation
    print("Docstar: Checking code debris findings...", flush=True)
    phase_start = time_module.monotonic()
    findings_dir = config.root_path / ".docstar" / "findings"
    if findings_dir.exists():
        for findings_file in sorted(findings_dir.rglob("*.findings.json")):
            try:
                data = json.loads(findings_file.read_text(encoding="utf-8"))
                source_path = Path(data["source"])
                # Skip findings for ignored files
                if _matches_ignore(source_path, config.ignore_patterns):
                    continue
                if _matches_ignore(source_path, docstarignore):
                    continue
                for finding in data.get("findings", []):
                    issues.append(AuditIssue(
                        path=source_path,
                        severity=finding["severity"],
                        category=finding["category"],
                        message=f"L{finding['line_start']}-{finding['line_end']}: {finding['description']}",
                        remediation=finding.get("suggestion", "Review and fix the identified issue"),
                        line_start=finding["line_start"],
                        line_end=finding["line_end"],
                    ))
            except (json.JSONDecodeError, KeyError):
                continue  # Skip malformed findings files
    if verbose:
        elapsed = time_module.monotonic() - phase_start
        print(f"  [{elapsed:.1f}s]", flush=True)

    # 4. Cross-reference validation (opt-in)
    if xref:
        print("Docstar: Validating documentation cross-references...", flush=True)
        phase_start = time_module.monotonic()
        xref_issues = validate_cross_references(config, on_progress=progress_cb)
        if verbose:
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s]", flush=True)
        for issue in xref_issues:
            issues.append(AuditIssue(
                path=issue.doc_path,
                severity=issue.severity,
                category="cross_reference",
                message=f"Cross-reference issue: {issue.description}",
                remediation=issue.remediation,
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


def format_audit_json(result: AuditResult) -> str:
    """Format audit result as JSON for CI/machine consumption."""
    return json.dumps({
        "passed": result.passed,
        "errors": sum(1 for i in result.issues if i.severity == "error"),
        "warnings": sum(1 for i in result.issues if i.severity == "warning"),
        "issues": [
            {
                "path": str(issue.path),
                "severity": issue.severity,
                "category": issue.category,
                "message": issue.message,
                "remediation": issue.remediation,
                "line_start": issue.line_start,
                "line_end": issue.line_end,
            }
            for issue in result.issues
        ],
    }, indent=2)
