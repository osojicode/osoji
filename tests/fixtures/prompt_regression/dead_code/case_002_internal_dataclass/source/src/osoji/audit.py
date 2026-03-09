"""Documentation audit orchestration."""

import json
import shutil
import time as time_module
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import Config
from .rate_limiter import RateLimiter, get_config_with_overrides
from .shadow import check_shadow_docs, generate_shadow_docs
from .debris import analyze_docs
from .deadcode import detect_dead_code
from .plumbing import detect_dead_plumbing
from .scorecard import Scorecard, build_scorecard
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


def _serialize_json(path: Path, data: dict) -> None:
    """Write a JSON file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


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
    dead_code: bool = False,
    dead_plumbing: bool = False,
    verbose: bool = False,
) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Osoji configuration
        fix_shadow: If True, auto-update stale shadow docs (Osoji owns them)
        dead_code: If True, detect cross-file dead code (LLM calls for ambiguous candidates)
        dead_plumbing: If True, detect unactuated config obligations (LLM calls)
        verbose: If True, show detailed per-file progress and timing
    """
    issues: list[AuditIssue] = []
    progress_cb = _make_progress_verbose(config) if verbose else _make_progress_default(config)
    osojiignore = config.load_osojiignore()

    # Shared rate limiter across all phases so token budgets are tracked globally
    rate_limiter = RateLimiter(get_config_with_overrides("anthropic"))

    # Clean stale analysis directory (fresh each run)
    analysis_root = config.analysis_root
    if analysis_root.exists():
        shutil.rmtree(analysis_root)

    # 1. Check shadow docs (auto-fix if enabled)
    print("Osoji: Checking shadow documentation...", flush=True)
    shadow_issues = check_shadow_docs(config)

    if fix_shadow and shadow_issues:
        print(f"Osoji: Auto-updating {len(shadow_issues)} shadow doc(s)...", flush=True)
        phase_start = time_module.monotonic()
        generate_shadow_docs(config, verbose=verbose, rate_limiter=rate_limiter)
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
            remediation="Run 'osoji shadow .' to update",
        ))

    # 2. Unified documentation analysis (replaces debris + xref)
    print("Osoji: Analyzing documentation...", flush=True)
    phase_start = time_module.monotonic()
    analysis_results = analyze_docs(config, on_progress=progress_cb, rate_limiter=rate_limiter)
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
    for item in analysis_results:
        analysis_path = config.analysis_docs_path_for(item.path)
        _serialize_json(analysis_path, {
            "path": str(item.path),
            "classification": item.classification,
            "confidence": item.confidence,
            "classification_reason": item.classification_reason,
            "matched_shadows": item.matched_shadows,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "description": f.description,
                    "shadow_ref": f.shadow_ref,
                    "evidence": f.evidence,
                    "remediation": f.remediation,
                }
                for f in item.findings
            ],
            "is_debris": item.is_debris,
            "topic_signature": item.topic_signature,
        })

    # 3. Surface code debris findings from shadow generation
    print("Osoji: Checking code debris findings...", flush=True)
    phase_start = time_module.monotonic()
    findings_dir = config.root_path / ".osoji" / "findings"
    if findings_dir.exists():
        for findings_file in sorted(findings_dir.rglob("*.findings.json")):
            try:
                data = json.loads(findings_file.read_text(encoding="utf-8"))
                source_path = Path(data["source"])
                # Skip findings for ignored files
                if _matches_ignore(source_path, config.ignore_patterns):
                    continue
                if _matches_ignore(source_path, osojiignore):
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
    dead_code_results = None
    if dead_code:
        print("Osoji: Scanning for cross-file dead code...", flush=True)
        phase_start = time_module.monotonic()
        dead_code_results = detect_dead_code(config, on_progress=progress_cb, rate_limiter=rate_limiter)
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

        # Serialize Phase 4 results (group by source_path)
        by_source: dict[str, list] = {}
        for item in dead_code_results:
            key = item.source_path.replace("\\", "/")
            if key not in by_source:
                by_source[key] = []
            by_source[key].append({
                "name": item.name,
                "kind": item.kind,
                "line_start": item.line_start,
                "line_end": item.line_end,
                "is_dead": item.is_dead,
                "confidence": item.confidence,
                "reason": item.reason,
                "remediation": item.remediation,
            })
        for source_path, verifications in by_source.items():
            out_path = config.analysis_deadcode_path_for(Path(source_path))
            _serialize_json(out_path, {
                "source_path": source_path,
                "verifications": verifications,
            })

    # 5. Dead plumbing detection (opt-in)
    plumbing_result = None
    if dead_plumbing:
        print("Osoji: Scanning for unactuated configuration...", flush=True)
        phase_start = time_module.monotonic()
        plumbing_result = detect_dead_plumbing(config, on_progress=progress_cb, rate_limiter=rate_limiter)
        if verbose:
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s]", flush=True)
        for item in plumbing_result.verifications:
            issues.append(AuditIssue(
                path=Path(item.source_path),
                severity="warning",
                category="unactuated_config",
                message=f"L{item.line_start}: field `{item.field_name}` — {item.trace}",
                remediation=item.remediation,
                line_start=item.line_start,
                line_end=item.line_end,
            ))

        # Serialize Phase 5 results (group by source_path)
        by_source_p: dict[str, list] = {}
        for item in plumbing_result.verifications:
            key = item.source_path.replace("\\", "/")
            if key not in by_source_p:
                by_source_p[key] = []
            by_source_p[key].append({
                "field_name": item.field_name,
                "schema_name": item.schema_name,
                "line_start": item.line_start,
                "line_end": item.line_end,
                "is_actuated": item.is_actuated,
                "confidence": item.confidence,
                "trace": item.trace,
                "remediation": item.remediation,
            })
        for source_path, verifications in by_source_p.items():
            out_path = config.analysis_plumbing_path_for(Path(source_path))
            _serialize_json(out_path, {
                "source_path": source_path,
                "verifications": verifications,
            })

    # 6. Scorecard (always runs)
    print("Osoji: Building scorecard...", flush=True)
    scorecard = build_scorecard(
        config,
        analysis_results=analysis_results,
        dead_code_results=dead_code_results if dead_code else None,
        plumbing_result=plumbing_result if dead_plumbing else None,
    )
    _serialize_json(config.scorecard_path, asdict(scorecard))

    return AuditResult(issues=issues, scorecard=scorecard)


def _format_scorecard_section(scorecard: Scorecard) -> list[str]:
    """Format the scorecard as markdown lines for insertion into the report."""
    lines: list[str] = []
    lines.append("## Scorecard\n")

    # Summary table
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Documentation coverage | {scorecard.coverage_pct:.0f}% |")
    lines.append(f"| Dead docs (debris) | {len(scorecard.dead_docs)} |")
    lines.append(f"| Accuracy errors / live doc | {scorecard.accuracy_errors_per_doc:.2f} |")
    lines.append(f"| Junk code fraction | {scorecard.junk_fraction:.1%} ({scorecard.junk_total_lines} lines in {scorecard.junk_file_count} files) |")
    if scorecard.enforcement_total_obligations is not None:
        lines.append(f"| Unactuated config | {scorecard.enforcement_unactuated}/{scorecard.enforcement_total_obligations} ({scorecard.enforcement_pct_unactuated:.0f}%) |")
    else:
        lines.append("| Unactuated config | — (not scanned) |")
    lines.append("")

    # Coverage by type
    if scorecard.coverage_by_type:
        lines.append("### Coverage by document type\n")
        lines.append("| Type | Coverage |")
        lines.append("|------|----------|")
        for cls, pct in sorted(scorecard.coverage_by_type.items()):
            lines.append(f"| {cls} | {pct:.0f}% |")
        lines.append("")

    # Dead docs list
    if scorecard.dead_docs:
        lines.append("### Dead documentation\n")
        for doc in scorecard.dead_docs:
            lines.append(f"- `{doc}`")
        lines.append("")

    # Accuracy by category
    if scorecard.accuracy_by_category:
        lines.append("### Accuracy errors by category\n")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat, count in sorted(scorecard.accuracy_by_category.items()):
            lines.append(f"| {cat} | {count} |")
        lines.append("")

    # Junk code by category
    if scorecard.junk_by_category:
        lines.append("### Junk code by category\n")
        lines.append("| Category | Items | Lines |")
        lines.append("|----------|-------|-------|")
        for cat in sorted(scorecard.junk_by_category.keys()):
            items = scorecard.junk_by_category[cat]
            cat_lines = scorecard.junk_by_category_lines.get(cat, 0)
            lines.append(f"| {cat} | {items} | {cat_lines} |")
        lines.append("")

    # Worst files by junk fraction
    worst = [e for e in scorecard.junk_entries if e.junk_fraction > 0.05][:5]
    if worst:
        lines.append("### Worst files by junk fraction\n")
        lines.append("| File | Junk % | Junk lines / Total |")
        lines.append("|------|--------|-------------------|")
        for entry in worst:
            lines.append(f"| `{entry.source_path}` | {entry.junk_fraction:.0%} | {entry.junk_lines}/{entry.total_lines} |")
        lines.append("")

    # Enforcement by schema
    if scorecard.enforcement_by_schema:
        lines.append("### Enforcement by schema\n")
        lines.append("| Schema | Unactuated | Fields |")
        lines.append("|--------|------------|--------|")
        for schema, info in sorted(scorecard.enforcement_by_schema.items()):
            fields = ", ".join(info["fields"])
            lines.append(f"| `{schema}` | {info['unactuated']} | {fields} |")
        lines.append("")

    # Missing phases note
    missing: list[str] = []
    if "dead_symbol" not in scorecard.junk_sources:
        missing.append("`--dead-code`")
    if scorecard.enforcement_total_obligations is None:
        missing.append("`--dead-plumbing`")
    if missing:
        lines.append(f"*Phases not run: {', '.join(missing)}. Re-run with those flags for a complete scorecard.*\n")

    return lines


def format_audit_report(result: AuditResult, verbose: bool = False) -> str:
    """Format audit result as agent-ready markdown report."""
    if result.passed and not result.has_warnings and result.scorecard is None:
        return "# Osoji Audit Passed\n\nNo issues found."

    lines = []

    if result.passed:
        lines.append("# Osoji Audit Passed")
    else:
        lines.append("# Osoji Audit Failed")

    lines.append("")

    # Insert scorecard at top
    if result.scorecard:
        lines.extend(_format_scorecard_section(result.scorecard))

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
        lines.append("To override findings, add rules to `.osoji/rules`")

    return "\n".join(lines)


def format_audit_json(result: AuditResult) -> str:
    """Format audit result as JSON for CI/machine consumption."""
    output = {
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
        output["scorecard"] = asdict(result.scorecard)
    return json.dumps(output, indent=2, default=str)
