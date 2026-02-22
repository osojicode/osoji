"""Documentation audit orchestration."""

import json
import time as time_module
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .shadow import check_shadow_docs, generate_shadow_docs
from .debris import analyze_docs
from .deadcode import detect_dead_code
from .scorecard import (
    Scorecard,
    build_scorecard,
    format_scorecard_markdown,
    scorecard_to_json,
    serialize_scorecard,
)
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
    scorecard: Scorecard | None = None

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


def _serialize_analysis_results(config: Config, analysis_results: list) -> None:
    """Serialize Phase 2 DocAnalysisResult objects to .docstar/analysis/docs/."""
    analysis_docs_dir = config.root_path / ".docstar" / "analysis" / "docs"
    analysis_docs_dir.mkdir(parents=True, exist_ok=True)

    for result in analysis_results:
        rel_path = str(result.path).replace("\\", "/")
        out_path = analysis_docs_dir / (rel_path + ".analysis.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "path": str(result.path),
            "classification": result.classification,
            "confidence": result.confidence,
            "classification_reason": result.classification_reason,
            "matched_shadows": result.matched_shadows,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                    "shadow_ref": f.shadow_ref,
                    "evidence": f.evidence,
                    "remediation": f.remediation,
                }
                for f in result.findings
            ],
            "is_debris": result.is_debris,
        }

        # Include topic_signature if present
        if hasattr(result, "topic_signature") and result.topic_signature:
            data["topic_signature"] = result.topic_signature

        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _serialize_dead_code_results(config: Config, dead_code_results: list) -> None:
    """Serialize Phase 4 DeadCodeVerification objects to .docstar/analysis/dead-code/."""
    if not dead_code_results:
        return

    dead_code_dir = config.root_path / ".docstar" / "analysis" / "dead-code"
    dead_code_dir.mkdir(parents=True, exist_ok=True)

    # Group by source_path
    by_source: dict[str, list] = {}
    for item in dead_code_results:
        by_source.setdefault(item.source_path, []).append(item)

    for source_path, verifications in by_source.items():
        rel_path = source_path.replace("\\", "/")
        out_path = dead_code_dir / (rel_path + ".deadcode.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "source_path": source_path,
            "verifications": [
                {
                    "name": v.name,
                    "kind": v.kind,
                    "line_start": v.line_start,
                    "line_end": v.line_end,
                    "is_dead": v.is_dead,
                    "confidence": v.confidence,
                    "reason": v.reason,
                    "remediation": v.remediation,
                }
                for v in verifications
            ],
        }

        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_audit(
    config: Config,
    fix_shadow: bool = True,
    dead_code: bool = False,
    verbose: bool = False,
) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Docstar configuration
        fix_shadow: If True, auto-update stale shadow docs (Docstar owns them)
        dead_code: If True, detect cross-file dead code (LLM calls for ambiguous candidates)
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

    # 2. Unified documentation analysis (replaces debris + xref)
    print("Docstar: Analyzing documentation...", flush=True)
    phase_start = time_module.monotonic()
    analysis_results = analyze_docs(config, on_progress=progress_cb)
    if verbose:
        elapsed = time_module.monotonic() - phase_start
        print(f"  [{elapsed:.1f}s]", flush=True)

    for item in analysis_results:
        if item.is_debris:
            issues.append(AuditIssue(
                path=item.path,
                severity="error",
                category="debris",
                message=f"Documentation debris: {item.classification_reason}",
                remediation="Delete this file",
            ))
        for finding in item.findings:
            evidence_tag = ""
            if finding.shadow_ref and finding.evidence:
                evidence_tag = f" [evidence: {finding.shadow_ref} — \"{finding.evidence}\"]"
            issues.append(AuditIssue(
                path=item.path,
                severity=finding.severity,
                category=f"doc_{finding.category}",
                message=f"{finding.description}{evidence_tag}",
                remediation=finding.remediation,
            ))

    # Serialize Phase 2 results
    _serialize_analysis_results(config, analysis_results)

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

    # 4. Cross-file dead code detection (opt-in)
    dead_code_results = []
    if dead_code:
        print("Docstar: Scanning for cross-file dead code...", flush=True)
        phase_start = time_module.monotonic()
        dead_code_results = detect_dead_code(config, on_progress=progress_cb)
        if verbose:
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s]", flush=True)
        for item in dead_code_results:
            issues.append(AuditIssue(
                path=Path(item.source_path),
                severity="warning",
                category="cross_file_dead_code",
                message=f"L{item.line_start}: {item.kind} `{item.name}` — {item.reason}",
                remediation=item.remediation,
                line_start=item.line_start,
                line_end=item.line_end,
            ))

        # Serialize Phase 4 results
        _serialize_dead_code_results(config, dead_code_results)

    # 5. Scorecard (always runs as final phase)
    print("Docstar: Building scorecard...", flush=True)
    phase_start = time_module.monotonic()
    scorecard = build_scorecard(
        config,
        analysis_results=analysis_results,
        dead_code_results=dead_code_results if dead_code else None,
    )
    serialize_scorecard(scorecard, config)
    if verbose:
        elapsed = time_module.monotonic() - phase_start
        print(f"  [{elapsed:.1f}s]", flush=True)

    return AuditResult(issues=issues, scorecard=scorecard)


def format_audit_report(result: AuditResult, verbose: bool = False) -> str:
    """Format audit result as agent-ready markdown report."""
    lines = []

    if result.passed and not result.has_warnings:
        lines.append("# Docstar Audit Passed")
        lines.append("")
        lines.append("No issues found.")
    elif result.passed:
        lines.append("# Docstar Audit Passed")
    else:
        lines.append("# Docstar Audit Failed")

    lines.append("")

    # Scorecard at the top as a summary dashboard
    if result.scorecard:
        lines.append(format_scorecard_markdown(result.scorecard))

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
    data = {
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
    }

    if result.scorecard:
        data["scorecard"] = scorecard_to_json(result.scorecard)

    return json.dumps(data, indent=2)
