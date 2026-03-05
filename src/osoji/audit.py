"""Documentation audit orchestration."""

import html as _html_mod
import json
import shutil
import time as time_module
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, SHADOW_DIR
from .junk import JunkAnalyzer, JunkAnalysisResult
from .deadcode import DeadCodeAnalyzer
from .plumbing import DeadPlumbingAnalyzer
from .junk_deps import DeadDepsAnalyzer
from .junk_cicd import DeadCICDAnalyzer
from .junk_orphan import OrphanedFilesAnalyzer
from .rate_limiter import RateLimiter, get_config_with_overrides
from .shadow import check_shadow_docs, generate_shadow_docs
from .doc_analysis import analyze_docs
from .scorecard import CoverageEntry, JunkCodeEntry, Scorecard, build_scorecard
from .walker import _matches_ignore
from tabulate import tabulate as _tabulate


# Registry of all junk analyzers. New analyzers are added here.
JUNK_ANALYZERS: list[type[JunkAnalyzer]] = [
    DeadCodeAnalyzer,
    DeadPlumbingAnalyzer,
    DeadDepsAnalyzer,
    DeadCICDAnalyzer,
    OrphanedFilesAnalyzer,
]


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


def _format_tokens_short(input_tokens: int, output_tokens: int) -> str:
    """Format token counts compactly, e.g. '42.1K^ 5.3Kv'."""
    if input_tokens == 0 and output_tokens == 0:
        return ""
    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
    return f"{_fmt(input_tokens)}^ {_fmt(output_tokens)}v"


def _serialize_json(path: Path, data: dict) -> None:
    """Write a JSON file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _make_progress_default(config: Config, rate_limiter=None):
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
        tok_str = ""
        if rate_limiter:
            in_tok, out_tok = rate_limiter.get_cumulative_tokens()
            tok_str = _format_tokens_short(in_tok, out_tok)
            if tok_str:
                tok_str = f" {tok_str}"
        print(f"\r  [{completed}/{total}] {pct:.0f}%{tok_str} {symbol} {relative.name}\033[K", end="", flush=True)
        if completed == total:
            print()
    return progress


def _make_progress_verbose(config: Config, rate_limiter=None):
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
        tok_str = ""
        if rate_limiter:
            in_tok, out_tok = rate_limiter.get_cumulative_tokens()
            tok_str = _format_tokens_short(in_tok, out_tok)
            if tok_str:
                tok_str = f" {tok_str}"
        print(f"  {symbol}{tok_str} {relative}", flush=True)
    return progress


def _resolve_enabled_flags(
    dead_code: bool = False,
    dead_plumbing: bool = False,
    dead_deps: bool = False,
    dead_cicd: bool = False,
    orphaned_files: bool = False,
    junk: bool = False,
) -> set[str]:
    """Map boolean parameters to a set of CLI flag strings for enabled analyzers.

    --junk enables all analyzers. Individual flags enable specific ones.
    """
    if junk:
        return {a().cli_flag for a in JUNK_ANALYZERS}
    flags: set[str] = set()
    if dead_code:
        flags.add("dead-code")
    if dead_plumbing:
        flags.add("dead-plumbing")
    if dead_deps:
        flags.add("dead-deps")
    if dead_cicd:
        flags.add("dead-cicd")
    if orphaned_files:
        flags.add("orphaned-files")
    return flags


def _serialize_junk_results(config: Config, analyzer_name: str, result: JunkAnalysisResult) -> None:
    """Serialize junk analysis results grouped by source file."""
    by_source: dict[str, list[dict]] = {}
    for item in result.findings:
        key = item.source_path.replace("\\", "/")
        by_source.setdefault(key, []).append({
            "name": item.name,
            "kind": item.kind,
            "category": item.category,
            "line_start": item.line_start,
            "line_end": item.line_end,
            "confidence": item.confidence,
            "reason": item.reason,
            "remediation": item.remediation,
            "original_purpose": item.original_purpose,
            "metadata": item.metadata,
        })
    for source_path, findings in by_source.items():
        out_path = config.analysis_junk_path_for(analyzer_name, Path(source_path))
        _serialize_json(out_path, {
            "source_path": source_path,
            "analyzer": analyzer_name,
            "findings": findings,
        })


def run_audit(
    config: Config,
    fix_shadow: bool = True,
    dead_code: bool = False,
    dead_plumbing: bool = False,
    dead_deps: bool = False,
    dead_cicd: bool = False,
    orphaned_files: bool = False,
    junk: bool = False,
    obligations: bool = False,
    verbose: bool = False,
) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Osoji configuration
        fix_shadow: If True, auto-update stale shadow docs (Osoji owns them)
        dead_code: If True, detect cross-file dead code (LLM calls for ambiguous candidates)
        dead_plumbing: If True, detect unactuated config obligations (LLM calls)
        dead_deps: If True, detect unused package dependencies (LLM calls)
        dead_cicd: If True, detect stale CI/CD pipeline elements (LLM calls)
        orphaned_files: If True, detect orphaned source files (LLM calls)
        junk: If True, run all junk analysis phases
        obligations: If True, check cross-file string contracts (no LLM calls)
        verbose: If True, show detailed per-file progress and timing
    """
    issues: list[AuditIssue] = []
    osojiignore = config.load_osojiignore()

    # Shared rate limiter across all phases so token budgets are tracked globally
    rate_limiter = RateLimiter(get_config_with_overrides("anthropic"))
    progress_cb = _make_progress_verbose(config, rate_limiter) if verbose else _make_progress_default(config, rate_limiter)

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
    findings_dir = config.root_path / SHADOW_DIR / "findings"
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

    # 3.5. Obligation checking (pure Python, no LLM)
    obligation_findings = []
    if obligations:
        print("Osoji: Checking cross-file obligations...", flush=True)
        phase_start = time_module.monotonic()
        from .facts import FactsDB
        from .obligations import run_all_contract_checks
        facts_db = FactsDB(config)
        obligation_findings = run_all_contract_checks(facts_db)
        for f in obligation_findings:
            issues.append(AuditIssue(
                path=Path(f.consumer_file),
                severity=f.severity,
                category=f"obligation_{f.finding_type}",
                message=f.description,
                remediation=f.remediation,
            ))
        if verbose:
            n_violations = sum(1 for f in obligation_findings if f.finding_type == "violation")
            n_implicit = sum(1 for f in obligation_findings if f.finding_type == "implicit_contract")
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s] {n_violations} violation(s), {n_implicit} implicit contract(s)", flush=True)

    # 4. Unified junk analysis (opt-in per analyzer)
    junk_results: dict[str, JunkAnalysisResult] = {}
    enabled_flags = _resolve_enabled_flags(dead_code=dead_code, dead_plumbing=dead_plumbing, dead_deps=dead_deps, dead_cicd=dead_cicd, orphaned_files=orphaned_files, junk=junk)

    for analyzer_cls in JUNK_ANALYZERS:
        analyzer = analyzer_cls()
        if analyzer.cli_flag not in enabled_flags:
            continue
        print(f"Osoji: Running {analyzer.description}...", flush=True)
        phase_start = time_module.monotonic()
        result = analyzer.analyze(config, on_progress=progress_cb, rate_limiter=rate_limiter)
        junk_results[analyzer.name] = result
        if verbose:
            elapsed = time_module.monotonic() - phase_start
            print(f"  [{elapsed:.1f}s]", flush=True)

        for item in result.findings:
            issues.append(AuditIssue(
                path=Path(item.source_path),
                severity="warning",
                category=item.category,
                message=f"L{item.line_start}: {item.kind} `{item.name}` — {item.reason}",
                remediation=item.remediation,
                line_start=item.line_start,
                line_end=item.line_end,
            ))
        _serialize_junk_results(config, analyzer.name, result)

    # 5. Scorecard (always runs)
    print("Osoji: Building scorecard...", flush=True)
    scorecard = build_scorecard(
        config,
        analysis_results=analysis_results,
        junk_results=junk_results if junk_results else None,
    )
    # Attach obligation counts if obligations phase ran
    if obligations and obligation_findings:
        scorecard.obligation_violations = sum(
            1 for f in obligation_findings if f.finding_type == "violation"
        )
        scorecard.obligation_implicit_contracts = sum(
            1 for f in obligation_findings if f.finding_type == "implicit_contract"
        )
    _serialize_json(config.scorecard_path, asdict(scorecard))

    # Print token summary
    in_tok, out_tok = rate_limiter.get_cumulative_tokens()
    total_tok = in_tok + out_tok
    if total_tok > 0:
        print(f"API tokens: {in_tok:,}^ {out_tok:,}v ({total_tok:,} total)", flush=True)

    result = AuditResult(issues=issues, scorecard=scorecard)
    serialize_audit_result(config, result)
    return result


def serialize_audit_result(config: Config, result: AuditResult) -> Path:
    """Persist AuditResult to .osoji/analysis/audit-result.json."""
    data = json.loads(format_audit_json(result))
    out_path = config.analysis_root / "audit-result.json"
    _serialize_json(out_path, data)
    return out_path


def load_audit_result(config: Config) -> AuditResult:
    """Load a previously-serialized AuditResult. Raises FileNotFoundError if missing."""
    path = config.analysis_root / "audit-result.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    issues = [
        AuditIssue(
            path=Path(i["path"]),
            severity=i["severity"],
            category=i["category"],
            message=i["message"],
            remediation=i["remediation"],
            line_start=i.get("line_start"),
            line_end=i.get("line_end"),
        )
        for i in data.get("issues", [])
    ]

    scorecard = None
    if "scorecard" in data:
        sc = data["scorecard"]
        scorecard = Scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path=e["source_path"],
                    topic_signature=e["topic_signature"],
                    covering_docs=e["covering_docs"],
                )
                for e in sc["coverage_entries"]
            ],
            coverage_pct=sc["coverage_pct"],
            covered_count=sc["covered_count"],
            total_source_count=sc["total_source_count"],
            coverage_by_type=sc["coverage_by_type"],
            type_covered_counts=sc["type_covered_counts"],
            type_total_counts=sc["type_total_counts"],
            dead_docs=sc["dead_docs"],
            total_accuracy_errors=sc["total_accuracy_errors"],
            live_doc_count=sc["live_doc_count"],
            accuracy_errors_per_doc=sc["accuracy_errors_per_doc"],
            accuracy_by_category=sc["accuracy_by_category"],
            junk_total_lines=sc["junk_total_lines"],
            junk_total_source_lines=sc["junk_total_source_lines"],
            junk_fraction=sc["junk_fraction"],
            junk_item_count=sc["junk_item_count"],
            junk_file_count=sc["junk_file_count"],
            junk_by_category=sc["junk_by_category"],
            junk_by_category_lines=sc["junk_by_category_lines"],
            junk_entries=[
                JunkCodeEntry(
                    source_path=e["source_path"],
                    total_lines=e["total_lines"],
                    junk_lines=e["junk_lines"],
                    junk_fraction=e["junk_fraction"],
                    items=e["items"],
                )
                for e in sc["junk_entries"]
            ],
            junk_sources=sc["junk_sources"],
            enforcement_total_obligations=sc.get("enforcement_total_obligations"),
            enforcement_unactuated=sc.get("enforcement_unactuated"),
            enforcement_pct_unactuated=sc.get("enforcement_pct_unactuated"),
            enforcement_by_schema=sc.get("enforcement_by_schema"),
            obligation_violations=sc.get("obligation_violations"),
            obligation_implicit_contracts=sc.get("obligation_implicit_contracts"),
        )

    return AuditResult(issues=issues, scorecard=scorecard)


def _table(headers: list[str], rows: list[list[str]], fmt: str = "simple") -> str:
    """Render a table using tabulate."""
    return _tabulate(rows, headers=headers, tablefmt=fmt)


def _format_scorecard_section(scorecard: Scorecard) -> list[str]:
    """Format the scorecard as aligned console tables for insertion into the report."""
    lines: list[str] = []
    lines.append("## Scorecard\n")

    # Summary table
    summary_rows = [
        ["Source file coverage", f"{scorecard.coverage_pct:.0f}% ({scorecard.covered_count}/{scorecard.total_source_count} files)"],
        ["Dead docs (debris)", str(len(scorecard.dead_docs))],
        ["Accuracy errors / live doc", f"{scorecard.accuracy_errors_per_doc:.2f}"],
        ["Junk code fraction", f"{scorecard.junk_fraction:.1%} ({scorecard.junk_total_lines} lines in {scorecard.junk_file_count} files)"],
    ]
    if scorecard.enforcement_total_obligations is not None:
        summary_rows.append(["Unactuated config", f"{scorecard.enforcement_unactuated}/{scorecard.enforcement_total_obligations} ({scorecard.enforcement_pct_unactuated:.0f}%)"])
    else:
        summary_rows.append(["Unactuated config", "— (not scanned)"])
    lines.append(_table(["Metric", "Value"], summary_rows))
    lines.append("")

    # Doc linkage by type
    if scorecard.coverage_by_type:
        lines.append("### Doc linkage by type\n")
        lines.append("*Fraction of docs of each type that link to at least one source file.*\n")
        type_rows = []
        for cls in sorted(scorecard.coverage_by_type.keys()):
            linked = scorecard.type_covered_counts.get(cls, 0)
            total = scorecard.type_total_counts.get(cls, 0)
            pct = scorecard.coverage_by_type[cls]
            type_rows.append([cls, str(linked), str(total), f"{pct:.0f}%"])
        lines.append(_table(["Type", "Linked", "Total", "%"], type_rows))
        lines.append("")

    # Uncovered source files
    uncovered = [e for e in scorecard.coverage_entries if not e.covering_docs]
    if uncovered:
        lines.append("### Uncovered source files\n")
        for entry in uncovered:
            purpose = ""
            if entry.topic_signature and entry.topic_signature.get("purpose"):
                purpose = f" — {entry.topic_signature['purpose']}"
            lines.append(f"- `{entry.source_path}`{purpose}")
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
        acc_rows = [[cat, str(count)] for cat, count in sorted(scorecard.accuracy_by_category.items())]
        lines.append(_table(["Category", "Count"], acc_rows))
        lines.append("")

    # Junk code by category
    if scorecard.junk_by_category:
        lines.append("### Junk code by category\n")
        junk_rows = []
        for cat in sorted(scorecard.junk_by_category.keys()):
            items = scorecard.junk_by_category[cat]
            cat_lines = scorecard.junk_by_category_lines.get(cat, 0)
            junk_rows.append([cat, str(items), str(cat_lines)])
        lines.append(_table(["Category", "Items", "Lines"], junk_rows))
        lines.append("")

    # Worst files by junk fraction
    worst = [e for e in scorecard.junk_entries if e.junk_fraction > 0.05][:5]
    if worst:
        lines.append("### Worst files by junk fraction\n")
        worst_rows = [
            [entry.source_path, f"{entry.junk_fraction:.0%}", f"{entry.junk_lines}/{entry.total_lines}"]
            for entry in worst
        ]
        lines.append(_table(["File", "Junk %", "Junk lines / Total"], worst_rows))
        lines.append("")

    # Enforcement by schema
    if scorecard.enforcement_by_schema:
        lines.append("### Enforcement by schema\n")
        enf_rows = []
        for schema, info in sorted(scorecard.enforcement_by_schema.items()):
            fields = ", ".join(info["fields"])
            enf_rows.append([schema, str(info["unactuated"]), fields])
        lines.append(_table(["Schema", "Unactuated", "Fields"], enf_rows))
        lines.append("")

    # Missing phases note — derived from JUNK_ANALYZERS registry so names
    # can't drift out of sync after refactors.
    missing: list[str] = []
    for analyzer_cls in JUNK_ANALYZERS:
        a = analyzer_cls()
        if a.name not in scorecard.junk_sources:
            missing.append(f"`--{a.cli_flag}`")
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

    infos = [i for i in result.issues if i.severity == "info"]
    if infos:
        lines.append("## Info (advisory)\n")
        for issue in infos:
            lines.append(f"- `{issue.path}`: {issue.message}")
        lines.append("")

    lines.append("---")
    lines.append(f"**Result**: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info(s)")

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
        "infos": sum(1 for i in result.issues if i.severity == "info"),
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


# ---------------------------------------------------------------------------
# HTML audit report
# ---------------------------------------------------------------------------

_HANKO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 100 100">'
    '<defs><mask id="hm"><rect width="100" height="100" fill="white"/>'
    '<rect x="44" y="0" width="14" height="30" fill="black"/></mask></defs>'
    '<circle cx="50" cy="50" r="38" fill="none" stroke="#fafafa" stroke-width="8"'
    ' stroke-dasharray="200 40" mask="url(#hm)"/>'
    '<circle cx="50" cy="50" r="6" fill="#fafafa"/>'
    '</svg>'
)

_AUDIT_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500;600&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@300;400&display=swap');

:root {
  --bg: #1a1917;
  --bg-panel: #211f1d;
  --bg-card: #2a2826;
  --border: #3a3835;
  --border-subtle: #2a2826;
  --text: #e0ddd6;
  --text-dim: #a8a49c;
  --healthy: #7aaa7e;
  --amber: #c9a06e;
  --coral: #d4715e;
  --dead: #7a766e;
  --accent: #d4715e;
  --accent-surface: #2e2220;
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: 'DM Sans', system-ui, sans-serif;
  font-weight: 300;
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
  padding: 0;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(26, 25, 23, 0.92);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 14px 32px;
  display: flex; align-items: center; gap: 16px;
}
.header-mark { display: flex; align-items: center; flex-shrink: 0; }
.header-wordmark {
  font-family: 'Cormorant Garamond', serif;
  font-size: 1.15rem; font-weight: 400;
  color: var(--text); letter-spacing: 0.04em;
  margin-left: 10px;
}
.header-divider {
  width: 1px; height: 20px;
  background: var(--border); margin: 0 4px;
}
.header-label {
  font-family: 'DM Mono', monospace;
  font-size: 0.7rem; font-weight: 300;
  color: var(--text-dim);
  letter-spacing: 0.15em; text-transform: uppercase;
}
.badge {
  display: inline-block; padding: 4px 14px;
  border-radius: 2px;
  font-family: 'DM Mono', monospace;
  font-size: 0.7rem; font-weight: 300;
  letter-spacing: 0.15em; text-transform: uppercase;
}
.badge-pass { background: rgba(122,170,126,0.15); color: var(--healthy); border: 1px solid rgba(122,170,126,0.3); }
.badge-fail { background: rgba(212,113,94,0.15); color: var(--coral); border: 1px solid rgba(212,113,94,0.3); }

.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem 2rem 4rem; }

/* Metric cards — CSS grid with hairline borders */
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px; background: var(--border);
  margin-bottom: 2rem;
}
.card {
  background: var(--bg-card);
  padding: 16px 20px;
  text-align: center;
  transition: background 0.2s;
  cursor: pointer;
  border-top: 3px solid var(--border);
}
.card:hover { background: var(--bg-panel); }
.card-green  { border-top-color: var(--healthy); }
.card-amber  { border-top-color: var(--amber); }
.card-coral  { border-top-color: var(--coral); }
.card-label {
  font-family: 'DM Mono', monospace;
  font-size: 0.7rem; font-weight: 300; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.2em; margin-bottom: 6px;
}
.card-value {
  font-family: 'Cormorant Garamond', serif;
  font-size: 2.5rem; font-weight: 300; color: var(--text);
}
.card-detail {
  font-size: 12px; color: var(--text-dim); margin-top: 4px;
}

/* Sections */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 0;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.12);
  animation: fadeUp 0.4s ease both;
}
.section:nth-child(2) { animation-delay: 0.06s; }
.section:nth-child(3) { animation-delay: 0.12s; }
.section:nth-child(4) { animation-delay: 0.18s; }
.section:nth-child(5) { animation-delay: 0.24s; }
.section-head {
  padding: 14px 20px;
  font-family: 'DM Mono', monospace;
  font-size: 0.7rem; font-weight: 300;
  color: var(--text);
  border-bottom: 1px solid var(--border);
  text-transform: uppercase; letter-spacing: 0.2em;
}
.section-body { padding: 20px; }
.section-body p { margin-bottom: 12px; color: var(--text-dim); font-size: 14px; }

/* Tables */
table {
  width: 100%; border-collapse: collapse;
  font-size: 14px; margin-bottom: 16px;
}
th {
  text-align: left; padding: 8px 12px;
  font-family: 'DM Mono', monospace;
  font-size: 0.65rem; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.15em;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  font-family: 'DM Mono', monospace;
  font-size: 0.75rem; font-weight: 300;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(212,113,94,0.04); }

/* Coverage bar */
.cov-bar-wrap {
  background: rgba(58,56,53,0.5);
  border-radius: 0; height: 4px;
  overflow: hidden; margin-bottom: 16px;
}
.cov-bar-fill {
  height: 100%; border-radius: 0;
  transition: width 0.5s ease;
}

/* Matrix icons */
.ok  { color: var(--healthy); font-weight: 600; }
.miss { color: var(--dead); opacity: 0.5; }

/* Lists */
ul.file-list { list-style: none; padding: 0; }
ul.file-list li {
  padding: 6px 0; font-family: 'DM Mono', monospace;
  font-size: 0.75rem; font-weight: 300;
  border-bottom: 1px solid var(--border-subtle);
}
ul.file-list li:last-child { border-bottom: none; }
.purpose { color: var(--text-dim); font-family: 'DM Sans', system-ui; }

details summary {
  cursor: pointer; color: var(--accent);
  font-family: 'DM Mono', monospace;
  font-size: 0.75rem; margin-bottom: 8px;
}

.footer {
  text-align: center; padding: 24px;
  font-family: 'DM Mono', monospace;
  font-size: 0.7rem; color: var(--dead);
  border-top: 1px solid var(--border);
}

html { scroll-behavior: smooth; }
"""


def _h(s: str) -> str:
    """Shortcut for html.escape."""
    return _html_mod.escape(str(s))


def _color_for_pct(pct: float) -> str:
    """Return CSS class suffix for a percentage value."""
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "amber"
    return "coral"


def _html_metric_card(label: str, value: str, detail: str, href: str, color: str) -> str:
    return (
        f'<a href="#{_h(href)}" style="text-decoration:none">'
        f'<div class="card card-{color}">'
        f'<div class="card-label">{_h(label)}</div>'
        f'<div class="card-value">{_h(value)}</div>'
        f'<div class="card-detail">{_h(detail)}</div>'
        f'</div></a>'
    )


def _html_coverage_section(scorecard: "Scorecard") -> str:
    """Build the coverage section HTML."""
    parts: list[str] = []
    parts.append('<div class="section" id="section-coverage">')
    parts.append('<div class="section-head">Coverage</div>')
    parts.append('<div class="section-body">')

    # Coverage bar
    pct = scorecard.coverage_pct
    color = f"var(--{_color_for_pct(pct).replace('green','healthy')})"
    parts.append(f'<div class="cov-bar-wrap"><div class="cov-bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>')
    parts.append(f'<p>{scorecard.covered_count}/{scorecard.total_source_count} source files covered ({pct:.0f}%)</p>')

    # By-type table
    if scorecard.coverage_by_type:
        parts.append('<table><thead><tr><th>Type</th><th>Linked</th><th>Total</th><th>%</th></tr></thead><tbody>')
        for cls in sorted(scorecard.coverage_by_type.keys()):
            linked = scorecard.type_covered_counts.get(cls, 0)
            total = scorecard.type_total_counts.get(cls, 0)
            type_pct = scorecard.coverage_by_type[cls]
            parts.append(f'<tr><td>{_h(cls)}</td><td>{linked}</td><td>{total}</td><td>{type_pct:.0f}%</td></tr>')
        parts.append('</tbody></table>')

    # Concept coverage matrix
    if scorecard.coverage_entries:
        diataxis_types = sorted({
            doc["classification"]
            for entry in scorecard.coverage_entries
            for doc in entry.covering_docs
        })
        if diataxis_types:
            collapse = len(scorecard.coverage_entries) > 50
            if collapse:
                parts.append(f'<details><summary>Coverage matrix ({len(scorecard.coverage_entries)} files)</summary>')
            else:
                parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text)">Coverage matrix</p>')
            parts.append('<table><thead><tr><th>Source file</th>')
            for dt in diataxis_types:
                parts.append(f'<th style="text-align:center">{_h(dt)}</th>')
            parts.append('</tr></thead><tbody>')
            for entry in scorecard.coverage_entries:
                doc_types = {doc["classification"] for doc in entry.covering_docs}
                parts.append(f'<tr><td>{_h(entry.source_path)}</td>')
                for dt in diataxis_types:
                    if dt in doc_types:
                        parts.append('<td style="text-align:center"><span class="ok">&#10003;</span></td>')
                    else:
                        parts.append('<td style="text-align:center"><span class="miss">&#10007;</span></td>')
                parts.append('</tr>')
            parts.append('</tbody></table>')
            if collapse:
                parts.append('</details>')

    # Uncovered files
    uncovered = [e for e in scorecard.coverage_entries if not e.covering_docs]
    if uncovered:
        parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text)">Uncovered source files ({len(uncovered)})</p>')
        parts.append('<ul class="file-list">')
        for entry in uncovered:
            purpose = ""
            if entry.topic_signature and entry.topic_signature.get("purpose"):
                purpose = f' <span class="purpose">— {_h(entry.topic_signature["purpose"])}</span>'
            parts.append(f'<li>{_h(entry.source_path)}{purpose}</li>')
        parts.append('</ul>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_accuracy_section(result: "AuditResult") -> str:
    """Build the accuracy section HTML."""
    scorecard = result.scorecard
    accuracy_issues = [i for i in result.issues if i.category.startswith("doc_") and i.severity == "error"]
    if not accuracy_issues and not scorecard.accuracy_by_category:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-accuracy">')
    parts.append('<div class="section-head">Accuracy</div>')
    parts.append('<div class="section-body">')
    parts.append(f'<p>{scorecard.total_accuracy_errors} error(s) across {scorecard.live_doc_count} live doc(s) '
                 f'({scorecard.accuracy_errors_per_doc:.2f} per doc)</p>')

    if scorecard.accuracy_by_category:
        parts.append('<table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody>')
        for cat, count in sorted(scorecard.accuracy_by_category.items()):
            parts.append(f'<tr><td>{_h(cat)}</td><td>{count}</td></tr>')
        parts.append('</tbody></table>')

    # Group accuracy issues by category
    by_cat: dict[str, list] = {}
    for issue in accuracy_issues:
        by_cat.setdefault(issue.category, []).append(issue)

    for cat in sorted(by_cat.keys()):
        parts.append(f'<p style="font-weight:400;color:var(--text);margin-top:12px">{_h(cat)}</p>')
        parts.append('<ul class="file-list">')
        for issue in by_cat[cat]:
            parts.append(f'<li>{_h(str(issue.path))}: {_h(issue.message)}</li>')
        parts.append('</ul>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_junk_section(result: "AuditResult") -> str:
    """Build the junk code section HTML."""
    scorecard = result.scorecard
    if not scorecard.junk_by_category and scorecard.junk_item_count == 0:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-junk">')
    parts.append('<div class="section-head">Junk Code</div>')
    parts.append('<div class="section-body">')
    parts.append(f'<p>{scorecard.junk_fraction:.1%} of source lines ({scorecard.junk_total_lines}/{scorecard.junk_total_source_lines}) '
                 f'across {scorecard.junk_file_count} file(s)</p>')

    # By category
    if scorecard.junk_by_category:
        parts.append('<table><thead><tr><th>Category</th><th>Items</th><th>Lines</th></tr></thead><tbody>')
        for cat in sorted(scorecard.junk_by_category.keys()):
            items = scorecard.junk_by_category[cat]
            cat_lines = scorecard.junk_by_category_lines.get(cat, 0)
            parts.append(f'<tr><td>{_h(cat)}</td><td>{items}</td><td>{cat_lines}</td></tr>')
        parts.append('</tbody></table>')

    # Worst files
    worst = [e for e in scorecard.junk_entries if e.junk_fraction > 0.05][:10]
    if worst:
        parts.append('<p style="font-weight:400;color:var(--text);margin-top:12px">Worst files</p>')
        parts.append('<table><thead><tr><th>File</th><th>Junk %</th><th>Junk / Total</th></tr></thead><tbody>')
        for entry in worst:
            parts.append(f'<tr><td>{_h(entry.source_path)}</td><td>{entry.junk_fraction:.0%}</td>'
                         f'<td>{entry.junk_lines}/{entry.total_lines}</td></tr>')
        parts.append('</tbody></table>')

    # Individual findings
    junk_issues = [i for i in result.issues if i.category in scorecard.junk_by_category
                   or i.category in ("dead_symbol", "unactuated_config", "commented_out_code",
                                     "dead_code", "unreachable_code")]
    if junk_issues:
        collapse = len(junk_issues) > 20
        if collapse:
            parts.append(f'<details><summary>All findings ({len(junk_issues)})</summary>')
        parts.append('<ul class="file-list">')
        for issue in junk_issues:
            parts.append(f'<li>{_h(str(issue.path))}: {_h(issue.message)}</li>')
        parts.append('</ul>')
        if collapse:
            parts.append('</details>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_dead_docs_section(scorecard: "Scorecard") -> str:
    """Build the dead docs section HTML."""
    if not scorecard.dead_docs:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-dead-docs">')
    parts.append('<div class="section-head">Dead Documentation</div>')
    parts.append('<div class="section-body">')
    parts.append(f'<p>{len(scorecard.dead_docs)} file(s) classified as debris</p>')
    parts.append('<ul class="file-list">')
    for doc in scorecard.dead_docs:
        parts.append(f'<li>{_h(doc)}</li>')
    parts.append('</ul>')
    parts.append('</div></div>')
    return "\n".join(parts)


def _html_enforcement_section(scorecard: "Scorecard") -> str:
    """Build the enforcement section HTML."""
    if scorecard.enforcement_by_schema is None:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-enforcement">')
    parts.append('<div class="section-head">Enforcement</div>')
    parts.append('<div class="section-body">')
    parts.append(f'<p>{scorecard.enforcement_unactuated}/{scorecard.enforcement_total_obligations} '
                 f'obligations unactuated ({scorecard.enforcement_pct_unactuated:.0f}%)</p>')

    if scorecard.enforcement_by_schema:
        parts.append('<table><thead><tr><th>Schema</th><th>Unactuated</th><th>Fields</th></tr></thead><tbody>')
        for schema, info in sorted(scorecard.enforcement_by_schema.items()):
            fields = ", ".join(info["fields"])
            parts.append(f'<tr><td>{_h(schema)}</td><td>{info["unactuated"]}</td><td>{_h(fields)}</td></tr>')
        parts.append('</tbody></table>')

    parts.append('</div></div>')
    return "\n".join(parts)


def format_audit_html(result: AuditResult) -> str:
    """Format audit result as a self-contained HTML dashboard."""
    scorecard = result.scorecard
    errors = [i for i in result.issues if i.severity == "error"]
    warnings = [i for i in result.issues if i.severity == "warning"]
    passed = result.passed

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>osojicode — Audit Report</title>')
    parts.append(f'<style>{_AUDIT_CSS}</style>')
    parts.append('</head><body>')

    # Header
    badge_cls = "badge-pass" if passed else "badge-fail"
    badge_text = "PASSED" if passed else "FAILED"
    parts.append(
        f'<div class="header">'
        f'<span class="header-mark">{_HANKO_SVG}</span>'
        f'<span class="header-wordmark">osojicode</span>'
        f'<span class="header-divider"></span>'
        f'<span class="header-label">Audit Report</span>'
        f'<span class="badge {badge_cls}" style="margin-left:auto">{badge_text}</span>'
        f'</div>'
    )

    parts.append('<div class="container">')

    # Metric cards
    if scorecard:
        cov_color = _color_for_pct(scorecard.coverage_pct)
        dead_color = "green" if len(scorecard.dead_docs) == 0 else "coral"
        err_color = "green" if scorecard.accuracy_errors_per_doc < 0.5 else ("amber" if scorecard.accuracy_errors_per_doc < 1.5 else "coral")
        junk_pct_val = scorecard.junk_fraction * 100
        junk_color = "green" if junk_pct_val < 5 else ("amber" if junk_pct_val < 15 else "coral")

        parts.append('<div class="cards">')
        parts.append(_html_metric_card(
            "Coverage", f"{scorecard.coverage_pct:.0f}%",
            f"{scorecard.covered_count}/{scorecard.total_source_count} files",
            "section-coverage", cov_color))
        parts.append(_html_metric_card(
            "Dead Docs", str(len(scorecard.dead_docs)),
            "debris files",
            "section-dead-docs", dead_color))
        parts.append(_html_metric_card(
            "Errors/Doc", f"{scorecard.accuracy_errors_per_doc:.2f}",
            f"{scorecard.total_accuracy_errors} total",
            "section-accuracy", err_color))
        parts.append(_html_metric_card(
            "Junk", f"{scorecard.junk_fraction:.1%}",
            f"{scorecard.junk_total_lines} lines",
            "section-junk", junk_color))
        parts.append('</div>')

        # Sections
        parts.append(_html_coverage_section(scorecard))
        parts.append(_html_accuracy_section(result))
        parts.append(_html_junk_section(result))
        parts.append(_html_dead_docs_section(scorecard))
        parts.append(_html_enforcement_section(scorecard))

    parts.append('</div>')  # container

    # Footer
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f'<div class="footer">{len(errors)} error(s), {len(warnings)} warning(s) &middot; {_h(now)}'
                 f'<br>osojicode</div>')

    parts.append('</body></html>')
    return "\n".join(parts)
