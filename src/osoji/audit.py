"""Documentation audit orchestration."""

import asyncio
import html as _html_mod
import json
import shutil
import time as time_module
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, SHADOW_DIR
from .diff import get_diff_files
from .findings import Finding
from .hasher import is_findings_current
from .hooks import find_git_root
from .junk import JunkAnalyzer, JunkAnalysisResult, load_shadow_content
from .deadcode import DeadCodeAnalyzer
from .deadparam import DeadParameterAnalyzer
from .plumbing import DeadPlumbingAnalyzer
from .junk_deps import DeadDepsAnalyzer
from .junk_cicd import DeadCICDAnalyzer
from .junk_orphan import OrphanedFilesAnalyzer
from .rate_limiter import RateLimiter, get_config_with_overrides
from .shadow import check_shadow_docs, generate_shadow_docs_async
from .doc_analysis import analyze_docs_async
from .junk_cicd import discover_cicd_files
from .llm.runtime import create_runtime
from .llm.errors import ProviderCircuitBreaker, classify_permanent_error
from .llm.types import ProviderPermanentError
from .scorecard import CoverageEntry, JunkCodeEntry, Scorecard, build_scorecard
from .walker import _matches_ignore
# V1-3: Phase 3 debris verification runs through the unified Triage stage. The
# debris evidence helpers live in claim_builder now (relocated from here) and are
# re-exported so existing call sites and tests keep importing them from osoji.audit.
from .claim_builder import (  # noqa: F401  (re-exported helpers)
    _extract_all_symbols_from_debris,
    _infer_variable_type,
    _lookup_type_definitions,
    build_debris_claims,
)
from .audit_manifest import (
    IncrementalAuditError,
    VerdictSession,
    cache_from_verdicts,
    current_version,
    get_head_commit,
    load_manifest,
    merge_verdicts,
    write_manifest,
)
from .triage import TRIAGE_SYSTEM_PROMPT
try:
    from tabulate import tabulate as _tabulate
except ModuleNotFoundError:
    def _tabulate(rows, headers, tablefmt="simple"):
        widths = [len(str(header)) for header in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))

        def format_row(row):
            return "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

        header_line = format_row(headers)
        separator = "  ".join("-" * width for width in widths)
        body = [format_row(row) for row in rows]
        return "\n".join([header_line, separator, *body])


# Registry of all junk analyzers. New analyzers are added here.
JUNK_ANALYZERS: list[type[JunkAnalyzer]] = [
    DeadCodeAnalyzer,
    DeadParameterAnalyzer,
    DeadPlumbingAnalyzer,
    DeadDepsAnalyzer,
    DeadCICDAnalyzer,
    OrphanedFilesAnalyzer,
]

# Valid phase identifiers for --exclude (discoverable via --help).
EXCLUDABLE_PHASES: list[str] = [
    "shadow", "doc-analysis", "debris", "obligations", "doc-prompts",
] + [cls().cli_flag for cls in JUNK_ANALYZERS]

# Map junk analyzer .name → .cli_flag for exclude_key tagging and display names.
_JUNK_NAME_TO_CLI_FLAG: dict[str, str] = {cls().name: cls().cli_flag for cls in JUNK_ANALYZERS}

# Map CLI analyzer flags → the producer prefix their findings carry in
# Finding.detector (see findings_adapter). Used for the V1-9 producer-scoped
# manifest merge.
_CLI_FLAG_TO_PRODUCER: dict[str, str] = {
    "dead-code": "deadcode",
    "dead-params": "deadparam",
    "dead-plumbing": "plumbing",
    "dead-deps": "deps",
    "dead-cicd": "cicd",
    "orphaned-files": "orphan",
}


@dataclass
class AuditIssue:
    """A single audit finding."""

    path: Path
    severity: str  # "error", "warning", or "info"
    category: str  # "debris", "stale_shadow", "missing_shadow"
    message: str
    remediation: str
    line_start: int | None = None
    line_end: int | None = None
    origin: dict | None = None  # {"source": "llm"|"static"|"hybrid", "plugin": str}
    exclude_key: str | None = None  # matches --exclude identifier for this phase
    contract_class: str | None = None  # obligations only: string-contract taxonomy class (V1-5c)
    # Triage outputs, threaded from the decided Finding when one exists.
    # Additive: the detector's heuristic `remediation` above is unchanged; these
    # ride alongside it. None whenever no decided Finding backs this issue
    # (Triage never ran for this phase, or the seam degraded — see
    # audit_manifest.py's VerdictSession for the same vocabulary).
    finding_id: str | None = None
    verdict: str | None = None
    confidence: float | None = None
    triage_reasoning: str | None = None
    suggested_fix: str | None = None


@dataclass
class AuditResult:
    """Complete audit result."""

    issues: list[AuditIssue] = field(default_factory=list)
    scorecard: Scorecard | None = None
    config_snapshot: dict[str, Any] | None = None
    doc_prompts: Any | None = None  # DocPromptsResult when --doc-prompts used

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


def _emit(config: Config, message: str = "", *, end: str = "\n") -> None:
    """Print a diagnostic line unless quiet mode is enabled."""

    if config.quiet:
        return
    print(message, end=end, flush=True)


def _record_degradation(config: Config, phase: str, exc: Exception) -> None:
    """Record a best-effort Triage/manifest seam failure.

    Uses ``getattr`` so the seams stay safe when ``run_audit_async`` hasn't
    attached the list (e.g. unit tests calling a phase function directly) —
    mirrors how junk_triage.py reads the V1-9 ``verdict_session`` attach.
    """
    degradations = getattr(config, "audit_degradations", None)
    if degradations is not None:
        degradations.append({"phase": phase, "error": str(exc)})


def _phase_result_or_degrade(config: Config, phase: str, outcome: Any, default: Any) -> Any:
    """Unwrap a ``return_exceptions`` gather result, degrading on failure.

    A phase that raised (an unhandled provider/analysis error escaping its own
    best-effort handling) is recorded as degraded and its empty ``default`` is
    substituted so the rest of the audit still serializes. A permanent
    (billing/auth) failure also trips the shared circuit breaker (belt and
    suspenders — the provider layer normally trips it first).
    """
    if isinstance(outcome, BaseException):
        if not isinstance(outcome, Exception):
            raise outcome  # never swallow KeyboardInterrupt/CancelledError
        permanent = classify_permanent_error(outcome)
        breaker = getattr(config, "provider_circuit_breaker", None)
        if permanent is not None and breaker is not None:
            breaker.trip(permanent)
        _record_degradation(config, phase, outcome)
        return default
    return outcome


def _note_breaker_degradation(config: Config, phase: str) -> None:
    """Record ``phase`` as degraded when the shared circuit breaker is tripped.

    decide_junk_claims absorbs a permanent (billing/auth) error to keep its
    findings (best-effort) rather than raising, so the phase's own ``except``
    never fires. This attributes the tripped breaker to the phase that ran the
    doomed LLM work, once — so degraded_phases names it. Idempotent per phase.
    """
    breaker = getattr(config, "provider_circuit_breaker", None)
    if breaker is None or not breaker.tripped:
        return
    degradations = getattr(config, "audit_degradations", None)
    if degradations is None or any(d["phase"] == phase for d in degradations):
        return
    degradations.append({"phase": phase, "error": str(breaker.error)})


def _degraded_phases(config: Config) -> list[str] | None:
    """Sorted, deduplicated phase labels for degradations recorded so far."""
    degradations = getattr(config, "audit_degradations", None)
    if not degradations:
        return None
    return sorted({d["phase"] for d in degradations})


def _make_progress_default(config: Config, rate_limiter=None):
    """Create an inline progress bar callback (carriage return, same line)."""
    def progress(completed: int, total: int, path: Path, status: str) -> None:
        if config.quiet:
            return
        pct = completed / total * 100 if total > 0 else 0
        symbols = {
            "ok": "[ok]",
            "debris": "[DEBRIS]",
            "error": "[FAIL]",
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
        if config.quiet:
            return
        symbols = {
            "ok": "[ok]",
            "debris": "[DEBRIS]",
            "error": "[FAIL]",
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
    dead_params: bool = False,
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
    if dead_params:
        flags.add("dead-params")
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
            "finding_id": item.finding_id,
            "verdict": item.verdict,
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
    dead_params: bool = False,
    dead_plumbing: bool = False,
    dead_deps: bool = False,
    dead_cicd: bool = False,
    orphaned_files: bool = False,
    junk: bool = False,
    obligations: bool = False,
    doc_prompts: bool = False,
    verbose: bool = False,
    exclude: set[str] | None = None,
    incremental: bool = False,
    since: str | None = None,
) -> AuditResult:
    """Run a complete documentation audit (sync entry point)."""
    return asyncio.run(run_audit_async(
        config,
        fix_shadow=fix_shadow,
        dead_code=dead_code,
        dead_params=dead_params,
        dead_plumbing=dead_plumbing,
        dead_deps=dead_deps,
        dead_cicd=dead_cicd,
        orphaned_files=orphaned_files,
        junk=junk,
        obligations=obligations,
        doc_prompts=doc_prompts,
        verbose=verbose,
        exclude=exclude,
        incremental=incremental,
        since=since,
    ))


async def run_audit_async(
    config: Config,
    fix_shadow: bool = True,
    dead_code: bool = False,
    dead_params: bool = False,
    dead_plumbing: bool = False,
    dead_deps: bool = False,
    dead_cicd: bool = False,
    orphaned_files: bool = False,
    junk: bool = False,
    obligations: bool = False,
    doc_prompts: bool = False,
    verbose: bool = False,
    exclude: set[str] | None = None,
    incremental: bool = False,
    since: str | None = None,
) -> AuditResult:
    """Run a complete documentation audit.

    Args:
        config: Osoji configuration
        fix_shadow: If True, auto-update stale shadow docs (Osoji owns them)
        dead_code: If True, detect cross-file dead code (LLM calls for ambiguous candidates)
        dead_params: If True, detect dead function parameters (LLM calls)
        dead_plumbing: If True, detect unactuated config obligations (LLM calls)
        dead_deps: If True, detect unused package dependencies (LLM calls)
        dead_cicd: If True, detect stale CI/CD pipeline elements (LLM calls)
        orphaned_files: If True, detect orphaned source files (LLM calls)
        junk: If True, run all junk analysis phases
        obligations: If True, check cross-file string contracts (no LLM calls)
        doc_prompts: If True, run concept-centric coverage + writing prompt generation (LLM calls)
        verbose: If True, show detailed per-file progress and timing
        exclude: Set of phase identifiers to skip (e.g. {"shadow", "dead-code"})
        incremental: If True, reuse cached Triage verdicts from the audit
            manifest for findings whose evidence fingerprint is unchanged
        since: Git ref to report changed files against; implies incremental
    """
    issues: list[AuditIssue] = []
    osojiignore = config.load_osojiignore()
    _exclude = exclude or set()

    # ── V1-9: incremental verdict cache ──
    # The fingerprint is the sole cache gate (it embeds impl_hash + the Claim
    # Builder schema version); --since only validates the environment and
    # reports the changed-file set. --force always wins: day-zero triage.
    use_cache = (incremental or since is not None) and not config.force
    if since is not None:
        repo_root = find_git_root(config.root_path)
        if repo_root is None:
            raise IncrementalAuditError(
                "--since requires the project to be inside a git repository"
            )
        try:
            changed = get_diff_files(repo_root, since, config)
        except RuntimeError as exc:
            raise IncrementalAuditError(str(exc)) from exc
        n_source = sum(1 for c in changed if c.is_source)
        n_doc = sum(1 for c in changed if c.is_doc)
        _emit(config, f"Osoji: {n_source} source / {n_doc} doc file(s) changed since {since}")
    previous_manifest = load_manifest(config.audit_manifest_path)
    manifest_current = (
        previous_manifest is not None
        and previous_manifest.get("osoji_version") == current_version()
    )
    verdict_cache: dict[tuple[str, str], dict] = {}
    if use_cache:
        if not manifest_current:
            _emit(config, "Osoji: no valid audit manifest for this osoji version - running day-zero audit")
        else:
            verdict_cache = cache_from_verdicts(previous_manifest["verdicts"])
    session = VerdictSession(cache=verdict_cache)
    config.verdict_session = session
    # Every best-effort Triage/manifest seam appends here on failure instead
    # of swallowing the exception silently.
    config.audit_degradations = []
    # osojicode/work#35: every Triage.decide_batch call this run appends its
    # decided findings here (see triage.py); serialized below as the
    # decided-findings ledger that `osoji corpus emit` reads.
    config.decided_ledger = []
    # #160: shared circuit breaker. create_runtime hands it to every phase's
    # provider; the first permanent (billing/auth) error trips it so remaining
    # LLM work short-circuits, and the run still reaches the terminal
    # serialization path before exiting nonzero with the billing cause.
    config.provider_circuit_breaker = ProviderCircuitBreaker()

    # Shared rate limiter across all phases so token budgets are tracked globally
    rate_limiter = RateLimiter(get_config_with_overrides(config.provider or "anthropic"))
    progress_cb = _make_progress_verbose(config, rate_limiter) if verbose else _make_progress_default(config, rate_limiter)

    # Clean stale analysis directory (fresh each run)
    analysis_root = config.analysis_root
    if analysis_root.exists():
        shutil.rmtree(analysis_root)

    # ── Phase 1: shadow docs (sequential — all later phases depend on this) ──
    _emit(config, "Osoji: Checking shadow documentation...")
    shadow_issues = check_shadow_docs(config)

    pre_shadow = rate_limiter.get_cumulative_tokens()
    if "shadow" in _exclude:
        if shadow_issues:
            _emit(config, f"  Note: shadow auto-fix excluded — {len(shadow_issues)} stale doc(s) will not be updated")
    elif fix_shadow and shadow_issues:
        _emit(config, f"Osoji: Auto-updating {len(shadow_issues)} shadow doc(s)...")
        phase_start = time_module.monotonic()
        await generate_shadow_docs_async(config, verbose=verbose, rate_limiter=rate_limiter)
        shadow_issues = []  # Cleared by regeneration
        elapsed = time_module.monotonic() - phase_start
        post_shadow = rate_limiter.get_cumulative_tokens()
        shadow_tok_str = _format_tokens_short(post_shadow[0] - pre_shadow[0], post_shadow[1] - pre_shadow[1])
        _emit(config, f"  [phase 1 shadow: {elapsed:.1f}s] {shadow_tok_str}")
    post_shadow = rate_limiter.get_cumulative_tokens()
    shadow_tokens = (post_shadow[0] - pre_shadow[0], post_shadow[1] - pre_shadow[1])

    for path, status in shadow_issues:
        issues.append(AuditIssue(
            path=path,
            severity="warning",  # Shadow issues are warnings (omission)
            category=f"{status}_shadow",
            message=f"Shadow documentation is {status}",
            remediation="Run 'osoji shadow .' to update",
            origin={"source": "static", "plugin": "shadow_check"},
            exclude_key="shadow",
        ))

    # ── Phases 2-4: run concurrently (no inter-phase data dependencies) ──

    # Pre-compute sync inputs needed by parallel phases
    raw_debris = _load_raw_debris(config, osojiignore) if "debris" not in _exclude else []
    enabled_flags = _resolve_enabled_flags(
        dead_code=dead_code, dead_params=dead_params,
        dead_plumbing=dead_plumbing, dead_deps=dead_deps,
        dead_cicd=dead_cicd, orphaned_files=orphaned_files, junk=junk,
    )
    # Remove excluded junk analyzers from enabled_flags
    enabled_flags -= _exclude

    # Apply exclusions: skip excluded phases, use no-op coroutines for gather
    async def _noop_phase2():
        return [], (0, 0)

    async def _noop_phase3():
        return set(), (0, 0), {}

    async def _noop_phase4():
        return {}, {}

    skip_doc_analysis = "doc-analysis" in _exclude
    skip_debris = "debris" in _exclude
    skip_obligations = "obligations" in _exclude

    phase2_coro = _noop_phase2() if skip_doc_analysis else _run_phase2_async(config, rate_limiter, progress_cb, verbose)
    phase3_coro = _noop_phase3() if skip_debris else _run_phase3_async(config, raw_debris, rate_limiter, verbose)
    phase3_5_coro = _run_phase3_5_async(config, obligations and not skip_obligations, rate_limiter, verbose)
    phase4_coro = _noop_phase4() if not enabled_flags else _run_phase4_async(config, rate_limiter, enabled_flags, progress_cb, verbose)

    # #160: gather with return_exceptions so one phase crashing (e.g. an
    # unhandled provider error in doc-analysis or a junk analyzer) never aborts
    # the run before serialization — the crashed phase is recorded as degraded
    # and substituted with its empty default so every other phase's completed
    # work is still collected and serialized below.
    gathered = await asyncio.gather(
        phase2_coro, phase3_coro, phase3_5_coro, phase4_coro,
        return_exceptions=True,
    )
    phase2_raw = _phase_result_or_degrade(config, "doc-analysis", gathered[0], ([], (0, 0)))
    phase3_raw = _phase_result_or_degrade(config, "debris", gathered[1], (set(), (0, 0), {}))
    phase3_5_raw = _phase_result_or_degrade(config, "obligations", gathered[2], ([], (0, 0), 0, 0))
    phase4_raw = _phase_result_or_degrade(config, "junk", gathered[3], ({}, {}))
    analysis_results, phase2_tokens = phase2_raw
    debris_result, phase3_tokens, debris_decided = phase3_raw
    obligation_findings, phase3_5_tokens, contract_triaged, contract_other = phase3_5_raw
    junk_results, phase4_tokens = phase4_raw

    suppressed_indices: set[int] = debris_result

    # Collect issues from Phase 2 (doc analysis)
    for item in analysis_results:
        if item.is_debris:
            issues.append(AuditIssue(
                path=item.path,
                severity="error",
                category="debris",
                message=f"Documentation debris: {item.classification_reason}",
                remediation="Delete this file",
                origin={"source": "llm", "plugin": "doc_analysis"},
                exclude_key="doc-analysis",
            ))
            # Debris items are never triaged (_triage_doc_findings skips
            # them), so .findings are raw, untriaged proposals -- moot for a
            # file whose verdict is "delete this file". Ship only the debris
            # error above; the per-item continue skips the raw proposals.
            continue
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
                origin={"source": "llm", "plugin": "doc_analysis"},
                exclude_key="doc-analysis",
                finding_id=finding.finding_id,
                verdict=finding.verdict,
                confidence=finding.confidence,
                triage_reasoning=finding.triage_reasoning,
                suggested_fix=finding.suggested_fix,
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
                    # Unified-Triage outputs; additive, may be None when a
                    # finding passed through unverified.
                    "verdict": f.verdict,
                    "confidence": f.confidence,
                    "triage_reasoning": f.triage_reasoning,
                    "suggested_fix": f.suggested_fix,
                    "finding_id": f.finding_id,
                }
                for f in item.findings
            ],
            "is_debris": item.is_debris,
            "topic_signature": item.topic_signature,
        })

    # Collect issues from Phase 3 (debris)
    debris_untriaged = 0
    for i, finding in enumerate(raw_debris):
        if i in suppressed_indices:
            continue
        # Triage overlay (additive): a decided Finding (when one exists for
        # this raw index) contributes its verdict/confidence/reasoning/
        # suggested-fix, plus a severity re-grade (Triage may demote a real
        # finding to a lower severity, never drop it outright) — the heuristic
        # severity/remediation stay the fallback, never dropped.
        decided = debris_decided.get(i)
        if decided is None or decided.verdict is None:
            # Kept without a Triage verdict (unclaimable, evidence gate unmet,
            # or a failed decide chunk) — counted for the scorecard and tagged
            # [untriaged] in the report (osoji#168 interim floor).
            debris_untriaged += 1
        heuristic_severity = finding["severity"]
        issues.append(AuditIssue(
            path=finding["source_path"],
            severity=(decided.severity or heuristic_severity) if decided is not None else heuristic_severity,
            category=finding["category"],
            message=f"L{finding['line_start']}-{finding['line_end']}: {finding['description']}",
            remediation=finding.get("suggestion", "Review and fix the identified issue"),
            line_start=finding["line_start"],
            line_end=finding["line_end"],
            origin={"source": "llm", "plugin": "code_debris"},
            exclude_key="debris",
            finding_id=decided.id if decided is not None else None,
            verdict=decided.verdict if decided is not None else None,
            confidence=decided.confidence if decided is not None else None,
            triage_reasoning=decided.triage_reasoning if decided is not None else None,
            suggested_fix=decided.suggested_fix if decided is not None else None,
        ))

    # Collect issues from Phase 3.5 (obligations)
    for f in obligation_findings:
        issues.append(AuditIssue(
            path=Path(f.consumer_file),
            severity=f.severity,
            category=f"obligation_{f.finding_type}",
            message=f.description,
            remediation=f.remediation,
            origin={"source": "hybrid", "plugin": "obligations"},
            exclude_key="obligations",
            contract_class=f.contract_class,
            finding_id=f.finding_id,
            verdict=f.verdict,
            confidence=f.triage_confidence,
            triage_reasoning=f.triage_reasoning,
            suggested_fix=f.suggested_fix,
        ))

    # Collect issues from Phase 4 (junk analyzers)
    for analyzer_name, junk_result in junk_results.items():
        junk_exclude_key = _JUNK_NAME_TO_CLI_FLAG.get(analyzer_name, analyzer_name)
        for item in junk_result.findings:
            prefix = "[AST] " if item.confidence_source == "ast_proven" else ""
            origin_source = "static" if item.confidence_source == "ast_proven" else "llm"
            issues.append(AuditIssue(
                path=Path(item.source_path),
                severity="warning",
                category=item.category,
                message=f"{prefix}L{item.line_start}: {item.kind} `{item.name}` — {item.reason}",
                remediation=item.remediation,
                line_start=item.line_start,
                line_end=item.line_end,
                origin={"source": origin_source, "plugin": analyzer_name},
                exclude_key=junk_exclude_key,
                finding_id=item.finding_id,
                verdict=item.verdict,
                confidence=item.confidence,
                triage_reasoning=item.reason,
                suggested_fix=item.remediation,
            ))
        _serialize_junk_results(config, analyzer_name, junk_result)

    # ── Phase 5: scorecard (sequential — needs all results) ──
    _emit(config, "Osoji: Building scorecard...")
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
    # CE-gap taxonomy counters (present whenever obligations ran, even if the
    # heuristic proposed nothing — a 0/0 is still a truthful "taxonomy healthy").
    if obligations and not skip_obligations:
        scorecard.contract_claims_triaged = contract_triaged
        scorecard.contract_claims_other = contract_other
    # Untriaged-debris floor (osoji#168): None when the phase didn't run — an
    # excluded phase must not read as a clean bill of health.
    if not skip_debris:
        scorecard.debris_untriaged = debris_untriaged
    # V1-9: cache effectiveness across every Triage seam this run
    scorecard.verdict_cache_hit_rate = session.hit_rate
    if use_cache and session.claims_seen:
        _emit(config, f"Verdict cache: {session.cache_hits}/{session.claims_seen} hit(s)")
    # Surface any best-effort degradation recorded so far (debris-triage,
    # obligations-triage — both run before this phase). manifest-write runs
    # after the scorecard is first serialized below, so this gets refreshed
    # and re-serialized once more near the end of the function.
    scorecard.degraded_phases = _degraded_phases(config)
    _serialize_json(config.scorecard_path, asdict(scorecard))

    # ── Phase 5.5: doc prompts (optional, after scorecard) ──
    doc_prompts_result = None
    phase55_tokens = (0, 0)
    if doc_prompts and "doc-prompts" not in _exclude:
        _emit(config, "Osoji: Building concept inventory and writing prompts...")
        phase_start = time_module.monotonic()
        from .doc_prompts import build_doc_prompts_async

        def _doc_prompts_progress(stage: str, in_tok: int, out_tok: int) -> None:
            tok_str = _format_tokens_short(in_tok, out_tok)
            cum_in, cum_out = rate_limiter.get_cumulative_tokens()
            cum_str = _format_tokens_short(cum_in, cum_out)
            _emit(config, f"  [doc prompts: {stage}] {tok_str} (cumulative: {cum_str})")

        doc_prompts_result, phase55_tokens = await build_doc_prompts_async(
            config, scorecard, rate_limiter=rate_limiter,
            on_stage_complete=_doc_prompts_progress,
        )
        # Populate concept-centric scorecard fields
        scorecard.concept_total = doc_prompts_result.total_concepts
        scorecard.concept_fully_documented = doc_prompts_result.fully_documented
        scorecard.concept_partially_documented = doc_prompts_result.partially_documented
        scorecard.concept_undocumented = doc_prompts_result.undocumented
        scorecard.concept_coverage_by_type = doc_prompts_result.coverage_by_type
        # Re-serialize scorecard with concept coverage
        _serialize_json(config.scorecard_path, asdict(scorecard))
        elapsed = time_module.monotonic() - phase_start
        tok_str = _format_tokens_short(phase55_tokens[0], phase55_tokens[1])
        _emit(config, f"  [phase 5.5 doc prompts: {elapsed:.1f}s] {tok_str} "
                     f"{doc_prompts_result.total_concepts} concepts, "
                     f"{doc_prompts_result.total_prompts} prompts")

    # ── Token summary ──
    # Collect per-phase token counts
    phase_tokens: dict[str, tuple[int, int]] = {}
    if shadow_tokens[0] + shadow_tokens[1] > 0:
        phase_tokens["Shadow docs"] = shadow_tokens
    if phase2_tokens[0] + phase2_tokens[1] > 0:
        phase_tokens["Doc analysis"] = phase2_tokens
    if phase3_tokens[0] + phase3_tokens[1] > 0:
        phase_tokens["Debris"] = phase3_tokens
    if phase3_5_tokens[0] + phase3_5_tokens[1] > 0:
        phase_tokens["Obligations"] = phase3_5_tokens
    for name, toks in phase4_tokens.items():
        display_name = _JUNK_NAME_TO_CLI_FLAG.get(name, name)
        if toks[0] + toks[1] > 0:
            phase_tokens[display_name] = toks
    if phase55_tokens[0] + phase55_tokens[1] > 0:
        phase_tokens["Doc prompts"] = phase55_tokens

    in_tok, out_tok = rate_limiter.get_cumulative_tokens()
    total_tok = in_tok + out_tok
    if total_tok > 0:
        _emit(config, f"API tokens: {in_tok:,}^ {out_tok:,}v ({total_tok:,} total)")
    if len(phase_tokens) > 1:
        _emit(config, "Token consumption by phase:")
        max_name_len = max(len(n) for n in phase_tokens)
        for name, (pt_in, pt_out) in phase_tokens.items():
            pt_total = pt_in + pt_out
            _emit(config, f"  {name:<{max_name_len}}  {pt_in:>10,}^ {pt_out:>8,}v  ({pt_total:,})")
        _emit(config, f"  {'-' * (max_name_len + 35)}")
        _emit(config, f"  {'Total':<{max_name_len}}  {in_tok:>10,}^ {out_tok:>8,}v  ({total_tok:,})")

    result = AuditResult(
        issues=issues,
        scorecard=scorecard,
        config_snapshot=config.config_snapshot,
        doc_prompts=doc_prompts_result,
    )
    serialize_audit_result(config, result)

    # ── V1-9: rewrite the verdict manifest (always — reading is opt-in) ──
    # Producer-scoped merge: entries from producers that ran are replaced
    # wholesale (disappeared findings drop out); entries from producers that
    # did not run this time are preserved. A previous manifest from a
    # different osoji version contributes nothing — its fingerprints can
    # never match again.
    try:
        producers: set[str] = set()
        if not skip_doc_analysis:
            producers.add("doc")
        if not skip_debris:
            producers.add("debris")
        if obligations and not skip_obligations:
            producers.add("obligations")
        producers |= {
            _CLI_FLAG_TO_PRODUCER[flag]
            for flag in enabled_flags
            if flag in _CLI_FLAG_TO_PRODUCER
        }
        prev_verdicts = previous_manifest["verdicts"] if manifest_current else {}
        write_manifest(
            config.audit_manifest_path,
            merge_verdicts(prev_verdicts, session.harvested, producers),
            commit=get_head_commit(config.root_path),
            version=current_version(),
        )
    except Exception as exc:
        # the manifest is an optimization; never fail the audit over it — but
        # its silent death kills --incremental and future closure detection,
        # so the degradation must still be recorded and visible.
        _record_degradation(config, "manifest-write", exc)
        _emit(config, f"[warn] manifest-write failed; findings kept unverified: {exc}")

    # manifest-write can add a degradation after the scorecard and audit
    # result were first serialized above; refresh and re-serialize both so
    # this run's persisted output agrees with the in-memory result returned
    # below (mirrors the Phase 5.5 doc-prompts re-serialize).
    scorecard.degraded_phases = _degraded_phases(config)
    _serialize_json(config.scorecard_path, asdict(scorecard))
    serialize_audit_result(config, result)

    # osojicode/work#35: the decided-findings ledger -- every triage verdict
    # decided this run, in one machine-readable file `osoji corpus emit`
    # reads to snapshot a sweep-proposed corpus case. Lives in analysis_root
    # (wiped at the top of this function) by design: one audit, one ledger.
    # Written even when empty so the file's mere presence signals "an audit
    # has run here" to corpus_emit's missing-ledger error.
    _serialize_json(config.analysis_root / "decided-findings.json", {
        "schema": "decided-findings/1",
        "commit": get_head_commit(config.root_path) or "unknown",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": config.decided_ledger,
    })

    # #160: everything above serialized this run's completed analysis (audit
    # result, scorecard with degraded_phases, decided-findings ledger). Only
    # now, with the terminal path done, surface a permanent provider failure so
    # the CLI exits nonzero with a message naming the billing/auth cause instead
    # of returning a silently-partial success.
    breaker = getattr(config, "provider_circuit_breaker", None)
    if breaker is not None and breaker.tripped:
        raise breaker.error

    return result


def _load_raw_debris(
    config: Config,
    osojiignore: list[str],
) -> list[dict]:
    """Load and filter debris findings from .osoji/findings/ (sync I/O)."""
    raw_debris: list[dict] = []
    findings_dir = config.root_path / SHADOW_DIR / "findings"
    if not findings_dir.exists():
        return raw_debris
    for findings_file in sorted(findings_dir.rglob("*.findings.json")):
        try:
            data = json.loads(findings_file.read_text(encoding="utf-8"))
            source_path_str = data["source"]
            source_path = Path(source_path_str)
            if not is_findings_current(
                data.get("source_hash"), data.get("impl_hash"),
                config.root_path / source_path,
            ):
                continue
            if _matches_ignore(source_path, config.ignore_patterns):
                continue
            if _matches_ignore(source_path, osojiignore):
                continue
            for finding in data.get("findings", []):
                raw_debris.append({
                    "source": source_path_str,
                    "source_path": source_path,
                    **finding,
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return raw_debris


async def _run_phase2_async(config, rate_limiter, progress_cb, verbose):
    """Phase 2: Unified documentation analysis."""
    _emit(config, "Osoji: Analyzing documentation...")
    phase_start = time_module.monotonic()
    logging_provider, _ = create_runtime(config, rate_limiter=rate_limiter)
    try:
        results = await analyze_docs_async(logging_provider, config, on_progress=progress_cb)
    finally:
        phase_tokens = (logging_provider.stats.total_input_tokens, logging_provider.stats.total_output_tokens)
        await logging_provider.close()
    elapsed = time_module.monotonic() - phase_start
    tok_str = _format_tokens_short(phase_tokens[0], phase_tokens[1])
    _emit(config, f"  [phase 2 doc analysis: {elapsed:.1f}s] {tok_str}")
    return results, phase_tokens


async def _run_phase3_async(config, raw_debris, rate_limiter, verbose):
    """Phase 3: Triage debris findings against gathered evidence.

    Builds self-sufficient claims for every debris finding (osoji#168 retired
    the legacy eligibility gate; findings whose evidence gate is unmet pass
    through unverified) and decides them through the shared chunked decide
    loop (work#57: the V1-5e A/B saw a whole-corpus single call go off-by-one
    from ~index 5; bounded chunks match every Phase 4 analyzer). A
    ``dismissed`` verdict suppresses the finding — preserving the prior behavior
    where a confirmed-false-positive was dropped. Best-effort: on any failure
    all findings are kept.

    Returns ``(suppressed_indices, phase_tokens, decided_by_index)``: the third
    element maps each eligible raw-debris index to its decided ``Finding``, so
    the caller can overlay verdict/confidence/reasoning/suggested-fix/severity
    onto the corresponding kept ``AuditIssue`` (additive; empty on any failure
    or when nothing needed verification).
    """
    from .junk_triage import decide_junk_claims
    _emit(config, "Osoji: Checking code debris findings...")
    phase_start = time_module.monotonic()
    suppressed_indices: set[int] = set()
    decided_by_index: dict[int, Finding] = {}
    phase_tokens = (0, 0)
    if raw_debris:
        try:
            claims, original_indices, would_escalate = build_debris_claims(config, raw_debris)
            if claims:
                # decide_junk_claims handles the verdict-session cache and
                # harvest itself (V1-9), so no manual session plumbing here.
                provider, _ = create_runtime(config, rate_limiter=rate_limiter)
                try:
                    decided, in_tok, out_tok = await decide_junk_claims(
                        claims, config, provider, system_prompt=TRIAGE_SYSTEM_PROMPT,
                    )
                finally:
                    await provider.close()
                for finding, orig_idx in zip(decided, original_indices):
                    decided_by_index[orig_idx] = finding
                    if finding.verdict == "dismissed":
                        suppressed_indices.add(orig_idx)
                phase_tokens = (in_tok, out_tok)
            if suppressed_indices and verbose:
                _emit(config, f"  Dismissed {len(suppressed_indices)} false positive debris finding(s)")
            # Dormant escalation tally (decision 0014): findings whose
            # require_any gate was unmet are kept unverified, not escalated.
            # The rate is a V1-4 falsifiability metric — a climbing rate says
            # the Claim Builder schema needs revision.
            if would_escalate and verbose:
                total = len(claims) + would_escalate
                rate = would_escalate / total if total else 0.0
                _emit(config, f"  {would_escalate} finding(s) lacked gatherable evidence "
                              f"(would-escalate; kept unverified; escalation rate {rate:.1%})")
            # #160: decide_junk_claims absorbs a permanent error to keep findings
            # (it never raises here), so attribute a tripped breaker to this phase.
            _note_breaker_degradation(config, "debris-triage")
        except Exception as exc:
            # Triage is best-effort; on failure, keep all findings — but the
            # degradation must be recorded and visible.
            _record_degradation(config, "debris-triage", exc)
            _emit(config, f"[warn] debris-triage failed; findings kept unverified: {exc}")
    elapsed = time_module.monotonic() - phase_start
    tok_str = _format_tokens_short(phase_tokens[0], phase_tokens[1])
    if tok_str:
        _emit(config, f"  [phase 3 debris triage: {elapsed:.1f}s] {tok_str}")
    elif verbose:
        _emit(config, f"  [phase 3 debris triage: {elapsed:.1f}s]")
    return suppressed_indices, phase_tokens, decided_by_index


def _overlay_verdict(cf, decided):
    """Record the Triage verdict's outputs on a ContractFinding, additively.

    ``contract_class`` plus the raw verdict/confidence/reasoning/suggested-fix
    and the decided Finding's id now ride along on new optional fields
    (``verdict``, ``triage_confidence``, ``triage_reasoning``, ``suggested_fix``,
    ``finding_id``) so the product boundary can surface what Triage decided.

    ``severity``/``remediation``/``confidence`` stay heuristic — untouched by
    this overlay. Two reasons: signal conservation (Triage's confirm/dismiss is
    the single variable this migration changes — it must not *also* re-scale
    the heuristic priors), and the heuristic remediation already carries the
    silent-value / loud-name framing the constraint requires preserved.
    """
    return replace(
        cf,
        contract_class=decided.contract_class,
        finding_id=decided.id,
        verdict=decided.verdict,
        triage_confidence=decided.confidence,
        triage_reasoning=decided.triage_reasoning,
        suggested_fix=decided.suggested_fix,
    )


async def _run_phase3_5_async(config, obligations_enabled, rate_limiter, verbose):
    """Phase 3.5: obligations — heuristic propose -> Claim Builder -> unified Triage.

    Unlike the other detector migrations, this one *adds* an LLM stage: the
    heuristic StringContractChecker proposes contract findings (unchanged), the
    Claim Builder assembles the file-tuple context, and unified Triage decides
    each claim under the three-gap rubric's five-class string-contract
    sub-rubric. A ``dismissed`` verdict suppresses the finding; confirmed and
    unverified (LLM-failure) findings are kept. Best-effort throughout — any
    failure keeps every finding unverified rather than dropping it (mirrors
    Phase 3).

    Returns ``(findings, tokens, triaged, other)``: ``triaged`` counts claims
    that received a verdict, ``other`` counts those the model routed to the
    string-contract taxonomy's ``other`` safety valve (the CE-gap numerator).
    """
    if not obligations_enabled:
        return [], (0, 0), 0, 0
    _emit(config, "Osoji: Checking cross-file obligations...")
    phase_start = time_module.monotonic()
    from .facts import FactsDB
    from .obligations import run_all_contract_checks
    from .findings_adapter import finding_from_contract
    from .evidence_builders import BuildContext
    from .claim_builder import build_claims
    from .junk_triage import decide_junk_claims

    facts_db = FactsDB(config)
    contract_findings = run_all_contract_checks(facts_db)   # PROPOSE (unchanged heuristic)

    kept = contract_findings
    phase_tokens = (0, 0)
    triaged = 0
    other = 0
    if contract_findings:
        try:
            findings = [finding_from_contract(cf, root=config.root_path) for cf in contract_findings]
            ctx = BuildContext(config, facts_db=facts_db)
            claims = build_claims(findings, ctx)            # -> _CONTRACT_ENTRY evidence
            provider, _ = create_runtime(config, rate_limiter=rate_limiter)
            try:
                decided, in_tok, out_tok = await decide_junk_claims(
                    claims, config, provider, system_prompt=TRIAGE_SYSTEM_PROMPT,
                )
            finally:
                await provider.close()
            phase_tokens = (in_tok, out_tok)
            kept = []
            for cf, df in zip(contract_findings, decided):
                if df.verdict is not None:
                    triaged += 1
                if df.contract_class == "other":
                    other += 1
                if df.verdict == "dismissed":
                    continue                                # dismissed = false positive -> suppress
                kept.append(_overlay_verdict(cf, df))       # confirmed OR unverified(None) kept
            # #160: decide_junk_claims absorbs a permanent error to keep findings
            # (it never raises here), so attribute a tripped breaker to this phase.
            _note_breaker_degradation(config, "obligations-triage")
        except Exception as exc:
            kept = contract_findings                        # best-effort: keep all, unverified
            _record_degradation(config, "obligations-triage", exc)
            _emit(config, f"[warn] obligations-triage failed; findings kept unverified: {exc}")
    if verbose:
        n_violations = sum(1 for f in kept if f.finding_type == "violation")
        n_implicit = sum(1 for f in kept if f.finding_type == "implicit_contract")
        elapsed = time_module.monotonic() - phase_start
        _emit(config, f"  [phase 3.5 obligations: {elapsed:.1f}s] {n_violations} violation(s), {n_implicit} implicit contract(s)")
        if triaged:
            rate = other / triaged
            _emit(config, f"  Triaged {triaged} contract claim(s); {other} routed to 'other' "
                          f"(CE-gap rate {rate:.1%})")
    return kept, phase_tokens, triaged, other


async def _run_phase4_async(config, rate_limiter, enabled_flags, progress_cb, verbose):
    """Phase 4: Run all enabled junk analyzers concurrently."""
    if not enabled_flags:
        return {}, {}

    symbols_dir = config.root_path / SHADOW_DIR / "symbols"

    # Build list of (analyzer, extra_kwargs) for enabled analyzers
    tasks: list[tuple[JunkAnalyzer, dict]] = []
    for analyzer_cls in JUNK_ANALYZERS:
        analyzer = analyzer_cls()
        if analyzer.cli_flag not in enabled_flags:
            continue

        if isinstance(analyzer, DeadCICDAnalyzer):
            # CI/CD doesn't need symbols, but needs cicd_files discovery
            cicd_files = discover_cicd_files(config)
            if not cicd_files:
                if not config.quiet:
                    print("  [skip] No CI/CD configuration files found.", flush=True)
                continue
            tasks.append((analyzer, {"cicd_files": cicd_files}))
        else:
            # Other analyzers require symbols data
            if not symbols_dir.exists():
                if not config.quiet:
                    print(f"  [skip] No symbols data found. Run 'osoji shadow .' first.", flush=True)
                continue
            tasks.append((analyzer, {}))

    if not tasks:
        return {}, {}

    async def _run_single(analyzer: JunkAnalyzer, extra_kwargs: dict) -> tuple[str, JunkAnalysisResult, tuple[int, int]]:
        _emit(config, f"Osoji: Running {analyzer.description}...")
        phase_start = time_module.monotonic()
        logging_provider, _ = create_runtime(config, rate_limiter=rate_limiter)
        try:
            result = await analyzer.analyze_async(
                logging_provider, config, progress_cb, **extra_kwargs,
            )
        finally:
            analyzer_tokens = (logging_provider.stats.total_input_tokens, logging_provider.stats.total_output_tokens)
            await logging_provider.close()
        elapsed = time_module.monotonic() - phase_start
        tok_str = _format_tokens_short(analyzer_tokens[0], analyzer_tokens[1])
        _emit(config, f"  [phase 4 {analyzer.name}: {elapsed:.1f}s] {tok_str}")
        return analyzer.name, result, analyzer_tokens

    raw_results = await asyncio.gather(*[
        _run_single(analyzer, kwargs)
        for analyzer, kwargs in tasks
    ])
    results_dict = {name: result for name, result, _ in raw_results}
    tokens_dict = {name: tokens for name, _, tokens in raw_results}
    return results_dict, tokens_dict


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
            origin=i.get("origin"),
            exclude_key=i.get("exclude_key"),
            contract_class=i.get("contract_class"),
            finding_id=i.get("finding_id"),
            verdict=i.get("verdict"),
            confidence=i.get("confidence"),
            triage_reasoning=i.get("triage_reasoning"),
            suggested_fix=i.get("suggested_fix"),
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
            contract_claims_triaged=sc.get("contract_claims_triaged"),
            contract_claims_other=sc.get("contract_claims_other"),
            debris_untriaged=sc.get("debris_untriaged"),
            verdict_cache_hit_rate=sc.get("verdict_cache_hit_rate"),
            concept_total=sc.get("concept_total"),
            concept_fully_documented=sc.get("concept_fully_documented"),
            concept_partially_documented=sc.get("concept_partially_documented"),
            concept_undocumented=sc.get("concept_undocumented"),
            concept_coverage_by_type=sc.get("concept_coverage_by_type"),
            degraded_phases=sc.get("degraded_phases"),
        )

    doc_prompts = None
    if isinstance(data.get("doc_prompts"), dict):
        doc_prompts = _deserialize_doc_prompts(data["doc_prompts"])

    return AuditResult(
        issues=issues,
        scorecard=scorecard,
        config_snapshot=data.get("config"),
        doc_prompts=doc_prompts,
    )


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
    if scorecard.concept_total is not None:
        summary_rows.append(["Concept coverage", f"{scorecard.concept_fully_documented}/{scorecard.concept_total} fully, "
                             f"{scorecard.concept_partially_documented} partial, "
                             f"{scorecard.concept_undocumented} undocumented"])
    if scorecard.contract_claims_triaged:
        other = scorecard.contract_claims_other or 0
        rate = other / scorecard.contract_claims_triaged
        summary_rows.append(["Contract taxonomy", f"{other}/{scorecard.contract_claims_triaged} 'other' "
                             f"({rate:.0%} CE-gap rate)"])
    if scorecard.debris_untriaged is not None:
        summary_rows.append(["Untriaged debris", str(scorecard.debris_untriaged)])
    degradation_value = ", ".join(scorecard.degraded_phases) if scorecard.degraded_phases else "none"
    summary_rows.append(["Triage degradation", degradation_value])
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
        # Count AST vs LLM per category from scorecard entries
        cat_ast_counts: dict[str, int] = {}
        cat_llm_counts: dict[str, int] = {}
        for entry in scorecard.junk_entries:
            for it in entry.items:
                cat = it["category"]
                cs = it.get("confidence_source", "llm_inferred")
                if cs == "ast_proven":
                    cat_ast_counts[cat] = cat_ast_counts.get(cat, 0) + 1
                else:
                    cat_llm_counts[cat] = cat_llm_counts.get(cat, 0) + 1
        for cat in sorted(scorecard.junk_by_category.keys()):
            items = scorecard.junk_by_category[cat]
            cat_lines = scorecard.junk_by_category_lines.get(cat, 0)
            ast_n = cat_ast_counts.get(cat, 0)
            llm_n = cat_llm_counts.get(cat, 0)
            if ast_n and llm_n:
                breakdown = f" ({ast_n} AST, {llm_n} LLM)"
            elif ast_n:
                breakdown = f" ({ast_n} AST)"
            else:
                breakdown = ""
            junk_rows.append([f"{cat}{breakdown}", str(items), str(cat_lines)])
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


def _is_test_path(path: str) -> bool:
    """Heuristic: path contains a test directory or test filename."""
    parts = path.replace("\\", "/").split("/")
    return any(p.startswith("test") or p == "tests" for p in parts)


_IMPLICIT_CONTRACT_PREAMBLE = """\
These findings identify string literals shared between source and test files.
They represent coupling that is often unintentional: the test is logically
asserting that an event occurred or an error was raised, but is mechanically
coupled to the exact wording of a message. If the message changes for any
reason — clarity, internationalisation, refactoring — the test will fail
without any behavioral regression occurring.

These are informational only. No action is required. If you choose to act:
- Prefer asserting on error types, status codes, or structured fields rather
  than message strings
- Where string assertions are intentional (e.g. testing exact CLI output),
  consider extracting the string to a shared constant so source and test stay
  in sync automatically

Findings below are observations, not verdicts."""


def _untriaged_tag(issue: AuditIssue) -> str:
    """`` [untriaged]`` for a kept debris finding without a Triage verdict.

    Debris-only: the other phases' verdict-``None`` issues were never Triage
    candidates, so the tag would be noise there (osoji#168 interim floor)."""
    if issue.exclude_key == "debris" and issue.verdict is None:
        return " [untriaged]"
    return ""


def format_audit_report(result: AuditResult) -> str:
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

    # Doc prompts summary
    if result.doc_prompts is not None:
        dp = result.doc_prompts
        lines.append("## Documentation Opportunities\n")
        lines.append(f"{dp.total_concepts} concepts. "
                     f"{dp.fully_documented} fully documented, "
                     f"{dp.partially_documented} partially, "
                     f"{dp.undocumented} undocumented. "
                     f"{dp.total_gaps} gap(s), {dp.total_prompts} prompt(s).\n")
        underdoc = [c for c in dp.concepts if c.missing_types]
        if underdoc:
            priority_order = {"high": 0, "medium": 1, "low": 2}
            underdoc.sort(key=lambda c: (priority_order.get(c.priority, 3), -c.priority_score))
            for c in underdoc:
                missing = ", ".join(c.missing_types)
                lines.append(f"- [{c.priority.upper()}] **{c.concept_name}** — missing: {missing}")
            lines.append("")

    errors = [i for i in result.issues if i.severity == "error"]
    warnings = [i for i in result.issues if i.severity == "warning"]

    if errors:
        lines.append("## Errors (blocking)\n")
        for issue in errors:
            phase_tag = f" [phase: {issue.exclude_key}]" if issue.exclude_key else ""
            lines.append(f"### `{issue.path}`{phase_tag}{_untriaged_tag(issue)}")
            lines.append(f"**Category**: {issue.category}")
            lines.append(f"**Issue**: {issue.message}")
            lines.append(f"**Remediation**: {issue.remediation}")
            if issue.suggested_fix and issue.suggested_fix != issue.remediation:
                meta = []
                if issue.verdict is not None:
                    meta.append(issue.verdict)
                if issue.confidence is not None:
                    meta.append(f"{issue.confidence:.2f}")
                meta_tag = f" ({', '.join(meta)})" if meta else ""
                lines.append(f"**Suggested fix (triage)**: {issue.suggested_fix}{meta_tag}")
            lines.append("")

    if warnings:
        lines.append("## Warnings (non-blocking)\n")
        for issue in warnings:
            phase_tag = f" [phase: {issue.exclude_key}]" if issue.exclude_key else ""
            lines.append(f"- `{issue.path}`: {issue.message}{phase_tag}{_untriaged_tag(issue)}")
        lines.append("")

    infos = [i for i in result.issues if i.severity == "info"]
    if infos:
        implicit_contracts = [i for i in infos if i.category == "obligation_implicit_contract"]
        other_infos = [i for i in infos if i.category != "obligation_implicit_contract"]

        if other_infos:
            lines.append("## Info (advisory)\n")
            for issue in other_infos:
                phase_tag = f" [phase: {issue.exclude_key}]" if issue.exclude_key else ""
                lines.append(f"- `{issue.path}`: {issue.message}{phase_tag}")
            lines.append("")

        if implicit_contracts:
            has_test_pairs = any(_is_test_path(str(ic.path)) for ic in implicit_contracts)
            lines.append("## Implicit String Contracts\n")
            if has_test_pairs:
                lines.append(_IMPLICIT_CONTRACT_PREAMBLE)
                lines.append("")
            for issue in implicit_contracts:
                phase_tag = f" [phase: {issue.exclude_key}]" if issue.exclude_key else ""
                lines.append(f"- `{issue.path}`: {issue.message}{phase_tag}")
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
                **({"origin": issue.origin} if issue.origin else {}),
                **({"exclude_key": issue.exclude_key} if issue.exclude_key else {}),
                **({"contract_class": issue.contract_class} if issue.contract_class else {}),
                **({"finding_id": issue.finding_id} if issue.finding_id else {}),
                **({"verdict": issue.verdict} if issue.verdict else {}),
                **({"confidence": issue.confidence} if issue.confidence is not None else {}),
                **({"triage_reasoning": issue.triage_reasoning} if issue.triage_reasoning else {}),
                **({"suggested_fix": issue.suggested_fix} if issue.suggested_fix else {}),
            }
            for issue in result.issues
        ],
    }
    if result.config_snapshot is not None:
        output["config"] = result.config_snapshot
    if result.scorecard:
        output["scorecard"] = asdict(result.scorecard)
    if result.doc_prompts is not None:
        output["doc_prompts"] = _serialize_doc_prompts(result.doc_prompts)
    return json.dumps(output, indent=2, default=str)


# ---------------------------------------------------------------------------
# HTML audit report
# ---------------------------------------------------------------------------

_HANKO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 100 100">'
    '<defs><mask id="hm"><rect width="100" height="100" fill="white"/>'
    '<rect x="44" y="0" width="14" height="30" fill="black"/></mask></defs>'
    '<circle cx="50" cy="50" r="38" fill="none" stroke="currentColor" stroke-width="8"'
    ' stroke-dasharray="200 40" mask="url(#hm)"/>'
    '<circle cx="50" cy="50" r="6" fill="currentColor"/>'
    '</svg>'
)

_AUDIT_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;500;600&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@300;400&display=swap');

:root {
  --font-serif: 'Cormorant Garamond', Georgia, serif;
  --font-sans: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'DM Mono', 'SF Mono', 'Fira Code', monospace;
  --radius-sm: 2px;
  --amber: #c9a06e;
}

[data-theme="light"] {
  --surface-1: #fafafa;
  --surface-2: #f5f4f0;
  --surface-3: #edecea;
  --surface-overlay: rgba(250,250,250,0.85);
  --text-1: #2c2a26;
  --text-2: #5c5850;
  --text-3: #8a8580;
  --border-subtle: #edecea;
  --border-default: #dedad4;
  --accent: #c4402f;
  --accent-surface: #faf0ee;
  --success: #5a8a5e;
  --warning: #d4715e;
  --info: #5c7a8a;
  --shadow-sm: 0 1px 3px rgba(44,42,38,0.04);
  --hanko-color: #2c2a26;
  --badge-pass-bg: rgba(90,138,94,0.12);
  --badge-pass-border: rgba(90,138,94,0.3);
  --badge-fail-bg: rgba(196,64,47,0.10);
  --badge-fail-border: rgba(196,64,47,0.25);
  --hover-tint: rgba(196,64,47,0.04);
  --bar-track: rgba(222,218,212,0.5);
}

[data-theme="dark"] {
  --surface-1: #1a1917;
  --surface-2: #211f1d;
  --surface-3: #2a2826;
  --surface-overlay: rgba(26,25,23,0.88);
  --text-1: #e0ddd6;
  --text-2: #a8a49c;
  --text-3: #7a766e;
  --border-subtle: #2a2826;
  --border-default: #3a3835;
  --accent: #d4715e;
  --accent-surface: #2e2220;
  --success: #7aaa7e;
  --warning: #d4715e;
  --info: #7a9aaa;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.2);
  --hanko-color: #fafafa;
  --badge-pass-bg: rgba(122,170,126,0.15);
  --badge-pass-border: rgba(122,170,126,0.3);
  --badge-fail-bg: rgba(212,113,94,0.15);
  --badge-fail-border: rgba(212,113,94,0.3);
  --hover-tint: rgba(212,113,94,0.04);
  --bar-track: rgba(58,56,53,0.5);
}

*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  font-weight: 300;
  background: var(--surface-1);
  color: var(--text-1);
  line-height: 1.65;
  padding: 0;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.header {
  position: sticky; top: 0; z-index: 100;
  background: var(--surface-overlay);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border-default);
  padding: 14px 32px;
  display: flex; align-items: center; gap: 16px;
}
.header-mark { display: flex; align-items: center; flex-shrink: 0; color: var(--hanko-color); }
.header-wordmark {
  font-family: var(--font-serif);
  font-size: 1.15rem; font-weight: 400;
  color: var(--text-1); letter-spacing: 0.04em;
  margin-left: 10px;
}
.header-divider {
  width: 1px; height: 20px;
  background: var(--border-default); margin: 0 4px;
}
.header-label {
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 300;
  color: var(--text-2);
  letter-spacing: 0.15em; text-transform: uppercase;
}
.badge {
  display: inline-block; padding: 4px 14px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 300;
  letter-spacing: 0.15em; text-transform: uppercase;
}
.badge-pass { background: var(--badge-pass-bg); color: var(--success); border: 1px solid var(--badge-pass-border); }
.badge-fail { background: var(--badge-fail-bg); color: var(--warning); border: 1px solid var(--badge-fail-border); }
.phase-tag { font-size: 0.75em; opacity: 0.6; font-family: var(--font-mono); }

.theme-toggle {
  background: none; border: 1px solid var(--border-default);
  color: var(--text-2); cursor: pointer;
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  margin-left: 12px; padding: 0;
}
.theme-toggle:hover { color: var(--text-1); border-color: var(--text-2); }
.theme-toggle .icon-sun,
.theme-toggle .icon-moon { width: 16px; height: 16px; }
[data-theme="dark"] .theme-toggle .icon-sun { display: none; }
[data-theme="dark"] .theme-toggle .icon-moon { display: block; }
[data-theme="light"] .theme-toggle .icon-sun { display: block; }
[data-theme="light"] .theme-toggle .icon-moon { display: none; }

.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem 2rem 4rem; }

/* Interpretive guide */
.guide {
  border: 1px solid var(--border-subtle);
  padding: 16px 20px;
  margin-bottom: 24px;
  font-size: 0.85rem;
  color: var(--text-2);
}
.guide-heading {
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 300;
  color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.15em;
  margin-bottom: 8px;
}

/* Metric cards — CSS grid with hairline borders */
.cards {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1px; background: var(--border-default);
  margin-bottom: 2rem;
}
.card {
  background: var(--surface-3);
  padding: 16px 20px;
  text-align: center;
  transition: background 0.2s;
  cursor: pointer;
  border-top: 3px solid var(--border-default);
}
.card:hover { background: var(--surface-2); }
.card-green  { border-top-color: var(--success); }
.card-amber  { border-top-color: var(--amber); }
.card-coral  { border-top-color: var(--warning); }
.card-label {
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 300; color: var(--text-2);
  text-transform: uppercase; letter-spacing: 0.2em; margin-bottom: 6px;
}
.card-value {
  font-family: var(--font-serif);
  font-size: 2.5rem; font-weight: 300; color: var(--text-1);
}
.card-detail {
  font-size: 12px; color: var(--text-2); margin-top: 4px;
}

/* Sections */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.section {
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: 0;
  margin-bottom: 24px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  animation: fadeUp 0.4s ease both;
}
.section:nth-child(2) { animation-delay: 0.06s; }
.section:nth-child(3) { animation-delay: 0.12s; }
.section:nth-child(4) { animation-delay: 0.18s; }
.section:nth-child(5) { animation-delay: 0.24s; }
.section-head {
  padding: 14px 20px;
  font-family: var(--font-mono);
  font-size: 0.7rem; font-weight: 300;
  color: var(--text-1);
  border-bottom: 1px solid var(--border-default);
  text-transform: uppercase; letter-spacing: 0.2em;
}
.section-body { padding: 20px; }
.section-body p { margin-bottom: 12px; color: var(--text-2); font-size: 14px; }

/* Tables */
table {
  width: 100%; border-collapse: collapse;
  font-size: 14px; margin-bottom: 16px;
}
th {
  text-align: left; padding: 8px 12px;
  font-family: var(--font-mono);
  font-size: 0.65rem; color: var(--text-2);
  text-transform: uppercase; letter-spacing: 0.15em;
  border-bottom: 1px solid var(--border-default);
}
td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  font-family: var(--font-mono);
  font-size: 0.75rem; font-weight: 300;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--hover-tint); }

/* Coverage bar */
.cov-bar-wrap {
  background: var(--bar-track);
  border-radius: 0; height: 4px;
  overflow: hidden; margin-bottom: 16px;
}
.cov-bar-fill {
  height: 100%; border-radius: 0;
  transition: width 0.5s ease;
}

/* Matrix icons */
.ok  { color: var(--success); font-weight: 600; }
.miss { color: var(--text-3); opacity: 0.5; }

/* Lists */
ul.file-list { list-style: none; padding: 0; }
ul.file-list li {
  padding: 6px 0; font-family: var(--font-mono);
  font-size: 0.75rem; font-weight: 300;
  border-bottom: 1px solid var(--border-subtle);
}
ul.file-list li:last-child { border-bottom: none; }
.purpose { color: var(--text-2); font-family: var(--font-sans); }

details summary {
  cursor: pointer; color: var(--accent);
  font-family: var(--font-mono);
  font-size: 0.75rem; margin-bottom: 8px;
}

.footer {
  text-align: center; padding: 24px;
  font-family: var(--font-mono);
  font-size: 0.7rem; color: var(--text-3);
  border-top: 1px solid var(--border-default);
}

html { scroll-behavior: smooth; }
"""


def _h(s: str) -> str:
    """Shortcut for html.escape."""
    return _html_mod.escape(str(s))


def _issue_loc(issue: "AuditIssue") -> str:
    """Return a line-number suffix like ':L10' or ':L10-L15' for an issue."""
    loc = ""
    if issue.line_start:
        if issue.line_end and issue.line_end != issue.line_start:
            loc = f":L{issue.line_start}-L{issue.line_end}"
        else:
            loc = f":L{issue.line_start}"
    if issue.exclude_key:
        loc += f' <span class="phase-tag">[{_h(issue.exclude_key)}]</span>'
    return loc


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


def _serialize_doc_prompts(dp: Any) -> dict:
    """Serialize DocPromptsResult for JSON output."""
    return {
        "concept_inventory": [
            {
                "concept_id": c.concept_id,
                "concept_name": c.concept_name,
                "concept_description": c.concept_description,
                "source_files": c.source_files,
                "concept_role": c.concept_role,
                "appropriate_types": c.appropriate_types,
                "existing_coverage": c.existing_coverage,
                "missing_types": c.missing_types,
                "coverage_status": c.coverage_status,
                "priority": c.priority,
                "priority_signals": c.priority_signals,
                "cluster_id": c.cluster_id,
            }
            for c in dp.concepts
        ],
        "writing_prompts": [
            {
                "prompt_id": p.prompt_id,
                "target_concepts": p.target_concepts,
                "diataxis_type": p.diataxis_type,
                "priority": p.priority,
                "prompt_text": p.prompt_text,
                "shadow_doc_excerpts": p.shadow_doc_excerpts,
                "related_docs": p.related_docs,
                "scope_constraints": p.scope_constraints,
                "output_guidance": p.output_guidance,
                "cluster_id": p.cluster_id,
            }
            for p in dp.writing_prompts
        ],
        "coverage_summary": {
            "total_concepts": dp.total_concepts,
            "fully_documented": dp.fully_documented,
            "partially_documented": dp.partially_documented,
            "undocumented": dp.undocumented,
            "coverage_by_type": dp.coverage_by_type,
            "total_gaps": dp.total_gaps,
            "total_prompts": dp.total_prompts,
        },
    }


def _deserialize_doc_prompts(data: dict) -> Any:
    """Reconstruct DocPromptsResult from a serialized dict."""
    from .doc_prompts import Concept, WritingPrompt, DocPromptsResult, _compute_priority

    concepts: list[Concept] = []
    for c in data.get("concept_inventory", []):
        concept = Concept(
            concept_id=c.get("concept_id", ""),
            concept_name=c.get("concept_name", ""),
            concept_description=c.get("concept_description", ""),
            source_files=c.get("source_files", []),
            concept_role=c.get("concept_role", "internal_utility"),
            appropriate_types=c.get("appropriate_types", []),
            appropriateness_rationale="",
            existing_coverage=c.get("existing_coverage", []),
            missing_types=c.get("missing_types", []),
            coverage_status=c.get("coverage_status", "undocumented"),
            priority=c.get("priority", "low"),
            priority_signals=c.get("priority_signals", []),
            cluster_id=c.get("cluster_id"),
        )
        _compute_priority(concept)
        concepts.append(concept)

    prompts: list[WritingPrompt] = []
    for p in data.get("writing_prompts", []):
        prompts.append(WritingPrompt(
            prompt_id=p.get("prompt_id", ""),
            target_concepts=p.get("target_concepts", []),
            diataxis_type=p.get("diataxis_type", ""),
            priority=p.get("priority", "low"),
            prompt_text=p.get("prompt_text", ""),
            shadow_doc_excerpts=p.get("shadow_doc_excerpts", []),
            related_docs=p.get("related_docs", []),
            scope_constraints=p.get("scope_constraints", ""),
            output_guidance=p.get("output_guidance", {}),
            cluster_id=p.get("cluster_id"),
        ))

    summary = data.get("coverage_summary", {})
    return DocPromptsResult(
        concepts=concepts,
        writing_prompts=prompts,
        total_concepts=summary.get("total_concepts", len(concepts)),
        fully_documented=summary.get("fully_documented", 0),
        partially_documented=summary.get("partially_documented", 0),
        undocumented=summary.get("undocumented", 0),
        coverage_by_type=summary.get("coverage_by_type", {}),
        total_gaps=summary.get("total_gaps", 0),
        total_prompts=summary.get("total_prompts", len(prompts)),
    )


def _html_doc_prompts_section(result: "AuditResult") -> str:
    """Build the Documentation Opportunities section HTML."""
    dp = result.doc_prompts
    if dp is None or not dp.concepts:
        return ""

    underdoc = [c for c in dp.concepts if c.missing_types]
    if not underdoc:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-doc-prompts">')
    parts.append('<div class="section-head">Documentation Opportunities</div>')
    parts.append('<div class="section-body">')

    parts.append(f'<p>{len(underdoc)} concept(s) underdocumented. '
                 f'{dp.total_prompts} writing prompt(s) generated.</p>')

    # Concept coverage summary table
    if dp.coverage_by_type:
        parts.append('<table><thead><tr><th>Type</th><th>Needed</th>'
                     '<th>Covered</th><th>%</th></tr></thead><tbody>')
        for t in sorted(dp.coverage_by_type.keys()):
            info = dp.coverage_by_type[t]
            needed = info.get("needed", 0)
            covered = info.get("covered", 0)
            pct = (covered / needed * 100) if needed > 0 else 0
            parts.append(f'<tr><td>{_h(t)}</td><td>{needed}</td>'
                         f'<td>{covered}</td><td>{pct:.0f}%</td></tr>')
        parts.append('</tbody></table>')

    # Build prompt lookup
    prompts_by_concept: dict[str, list] = {}
    for p in dp.writing_prompts:
        for cid in p.target_concepts:
            prompts_by_concept.setdefault(cid, []).append(p)

    # Priority groups
    priority_order = {"high": 0, "medium": 1, "low": 2}
    sorted_concepts = sorted(underdoc, key=lambda c: (priority_order.get(c.priority, 3), -c.priority_score))

    for concept in sorted_concepts:
        badge_color = {"high": "var(--warning)", "medium": "var(--amber)", "low": "var(--text-3)"}.get(concept.priority, "var(--text-3)")
        missing_str = ", ".join(concept.missing_types)
        parts.append('<details>')
        parts.append(f'<summary>'
                     f'<span style="display:inline-block;padding:2px 8px;'
                     f'font-size:0.65rem;font-weight:500;color:{badge_color};'
                     f'border:1px solid {badge_color};margin-right:8px;'
                     f'text-transform:uppercase;letter-spacing:0.1em">'
                     f'{_h(concept.priority.upper())}</span>'
                     f'{_h(concept.concept_name)} — missing: {_h(missing_str)}'
                     f'</summary>')
        parts.append('<div style="padding:8px 0 16px 24px">')
        parts.append(f'<p>{_h(concept.concept_description)}</p>')

        # Current coverage
        if concept.existing_coverage:
            existing = ", ".join(
                f"{d['diataxis_type']} ({d['doc_path']})"
                for d in concept.existing_coverage
            )
            parts.append(f'<p><strong>Current coverage:</strong> {_h(existing)}</p>')

        # Why it matters
        if concept.priority_signals:
            parts.append(f'<p><strong>Why it matters:</strong> {_h(", ".join(concept.priority_signals))}</p>')

        # Writing prompts
        concept_prompts = prompts_by_concept.get(concept.concept_id, [])
        for p in concept_prompts:
            parts.append('<details style="margin-top:8px">')
            parts.append(f'<summary>Writing prompt: {_h(p.diataxis_type)}</summary>')
            parts.append(f'<pre style="white-space:pre-wrap;font-size:0.75rem;'
                         f'padding:12px;background:var(--surface-3);'
                         f'border:1px solid var(--border-default);margin-top:8px;'
                         f'max-height:400px;overflow:auto">{_h(p.prompt_text)}</pre>')
            parts.append(f'<button onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)" '
                         f'style="margin-top:4px;padding:4px 12px;font-size:0.7rem;'
                         f'cursor:pointer;background:var(--surface-2);border:1px solid var(--border-default);'
                         f'color:var(--text-2)">Copy prompt</button>')
            parts.append('</details>')

        parts.append('</div></details>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_coverage_section(scorecard: "Scorecard", shadow_content: dict[str, str] | None = None) -> str:
    """Build the coverage section HTML."""
    parts: list[str] = []
    parts.append('<div class="section" id="section-coverage">')
    parts.append('<div class="section-head">Coverage</div>')
    parts.append('<div class="section-body">')

    # Coverage bar
    pct = scorecard.coverage_pct
    color = f"var(--{_color_for_pct(pct).replace('green','success').replace('coral','warning')})"
    parts.append(f'<div class="cov-bar-wrap"><div class="cov-bar-fill" style="width:{pct:.0f}%;background:{color}"></div></div>')
    parts.append(f'<p>{scorecard.covered_count}/{scorecard.total_source_count} source files covered ({pct:.0f}%)</p>')

    # Concept-centric coverage (when available)
    if scorecard.concept_total is not None:
        parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text-1)">Concept coverage</p>')
        parts.append(f'<p>{scorecard.concept_total} concept(s). '
                     f'{scorecard.concept_fully_documented} fully documented, '
                     f'{scorecard.concept_partially_documented} partially, '
                     f'{scorecard.concept_undocumented} undocumented.</p>')
        if scorecard.concept_coverage_by_type:
            parts.append('<table><thead><tr><th>Type</th><th>Needed</th>'
                         '<th>Covered</th><th>%</th></tr></thead><tbody>')
            for t in sorted(scorecard.concept_coverage_by_type.keys()):
                info = scorecard.concept_coverage_by_type[t]
                needed = info.get("needed", 0)
                covered = info.get("covered", 0)
                pct = (covered / needed * 100) if needed > 0 else 0
                parts.append(f'<tr><td>{_h(t)}</td><td>{needed}</td>'
                             f'<td>{covered}</td><td>{pct:.0f}%</td></tr>')
            parts.append('</tbody></table>')

    # By-type table (doc linkage)
    if scorecard.coverage_by_type:
        parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text-1)">Documentation linkage</p>')
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
                parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text-1)">Coverage matrix</p>')
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
                # Shadow doc preview row
                if shadow_content and entry.source_path in shadow_content:
                    preview = shadow_content[entry.source_path][:2000]
                    col_span = 1 + len(diataxis_types)
                    parts.append(
                        f'<tr><td colspan="{col_span}" style="padding:0">'
                        f'<details style="margin:0;padding:4px 8px">'
                        f'<summary style="font-size:0.7rem;color:var(--text-3);cursor:pointer">Shadow doc preview</summary>'
                        f'<pre style="white-space:pre-wrap;font-size:0.7rem;padding:8px;'
                        f'background:var(--surface-3);border:1px solid var(--border-default);'
                        f'max-height:300px;overflow:auto;margin:4px 0">{_h(preview)}</pre>'
                        f'</details></td></tr>'
                    )
            parts.append('</tbody></table>')
            if collapse:
                parts.append('</details>')

    # Uncovered files
    uncovered = [e for e in scorecard.coverage_entries if not e.covering_docs]
    if uncovered:
        parts.append(f'<p style="margin-top:16px;font-weight:400;color:var(--text-1)">Uncovered source files ({len(uncovered)})</p>')
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
    if scorecard is None:
        return ""
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
        parts.append(f'<p style="font-weight:400;color:var(--text-1);margin-top:12px">{_h(cat)}</p>')
        parts.append('<ul class="file-list">')
        for issue in by_cat[cat]:
            fix_tag = ""
            if issue.suggested_fix and issue.suggested_fix != issue.remediation:
                fix_tag = (
                    f'<br><span style="color:var(--text-3)">'
                    f'Suggested fix (triage): {_h(issue.suggested_fix)}</span>'
                )
            parts.append(f'<li>{_h(str(issue.path))}{_issue_loc(issue)}: {_h(issue.message)}{fix_tag}</li>')
        parts.append('</ul>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_junk_section(result: "AuditResult") -> str:
    """Build the junk code section HTML."""
    scorecard = result.scorecard
    if scorecard is None:
        return ""
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
        parts.append('<p style="font-weight:400;color:var(--text-1);margin-top:12px">Worst files</p>')
        parts.append('<table><thead><tr><th>File</th><th>Junk %</th><th>Junk / Total</th></tr></thead><tbody>')
        for entry in worst:
            parts.append(f'<tr><td>{_h(entry.source_path)}</td><td>{entry.junk_fraction:.0%}</td>'
                         f'<td>{entry.junk_lines}/{entry.total_lines}</td></tr>')
        parts.append('</tbody></table>')

    # Individual findings
    junk_categories = set(scorecard.junk_by_category.keys())
    junk_issues = [i for i in result.issues if i.category in junk_categories]
    if junk_issues:
        collapse = len(junk_issues) > 20
        if collapse:
            parts.append(f'<details><summary>All findings ({len(junk_issues)})</summary>')
        parts.append('<ul class="file-list">')
        for issue in junk_issues:
            parts.append(f'<li>{_h(str(issue.path))}{_issue_loc(issue)}: {_h(issue.message)}</li>')
        parts.append('</ul>')
        if collapse:
            parts.append('</details>')

    # Phases not run notice
    missing: list[str] = []
    for analyzer_cls in JUNK_ANALYZERS:
        a = analyzer_cls()
        if a.name not in scorecard.junk_sources:
            missing.append(f"--{a.cli_flag}")
    if missing:
        parts.append(f'<p style="font-style:italic;color:var(--text-3);margin-top:12px">'
                     f'Phases not run: {_h(", ".join(missing))}. Re-run with those flags for a complete scorecard.</p>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_file_health_section(result: "AuditResult") -> str:
    """Build the file health table section HTML."""
    from .observatory import _compute_file_health

    scorecard = result.scorecard
    if scorecard is None:
        return ""

    # Build per-file data from scorecard
    # shadow coverage: set of covered source paths
    covered_paths = set()
    for entry in scorecard.coverage_entries:
        if entry.covering_docs:
            covered_paths.add(entry.source_path)

    # junk fraction per file
    junk_map: dict[str, float] = {}
    for je in scorecard.junk_entries:
        junk_map[je.source_path] = je.junk_fraction

    # issues per file
    errors_map: dict[str, int] = {}
    warnings_map: dict[str, int] = {}
    for issue in result.issues:
        p = str(issue.path).replace("\\", "/")
        if issue.severity == "error":
            errors_map[p] = errors_map.get(p, 0) + 1
        elif issue.severity == "warning":
            warnings_map[p] = warnings_map.get(p, 0) + 1

    # Collect all files from coverage entries
    rows: list[tuple[str, float | None, bool, float, int, int]] = []
    for entry in scorecard.coverage_entries:
        fp = entry.source_path
        shadow_exists = fp in covered_paths
        jf = junk_map.get(fp, 0.0)
        ec = errors_map.get(fp, 0)
        wc = warnings_map.get(fp, 0)
        metrics = {"error_count": ec, "warning_count": wc, "junk_fraction": jf}
        health = _compute_file_health(metrics, shadow_exists, False)
        rows.append((fp, health, shadow_exists, jf, ec, wc))

    # Only show files with some signal
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return ""

    # Sort by health ascending (worst first)
    rows.sort(key=lambda r: r[1])

    parts: list[str] = []
    parts.append('<div class="section" id="section-file-health">')
    parts.append('<div class="section-head">File Health</div>')
    parts.append('<div class="section-body">')

    collapse = len(rows) > 50
    if collapse:
        parts.append(f'<details><summary>{len(rows)} files</summary>')

    parts.append('<table><thead><tr>'
                 '<th>File</th><th>Health</th><th>Shadow</th>'
                 '<th>Junk %</th><th>Errors</th><th>Warnings</th>'
                 '</tr></thead><tbody>')
    for fp, health, shadow, jf, ec, wc in rows:
        h_val = health if health is not None else 0.0
        if h_val >= 0.8:
            h_color = "var(--success)"
        elif h_val >= 0.5:
            h_color = "var(--amber)"
        else:
            h_color = "var(--warning)"
        shadow_mark = '<span class="ok">&#10003;</span>' if shadow else '<span class="miss">&#10007;</span>'
        parts.append(
            f'<tr><td>{_h(fp)}</td>'
            f'<td style="color:{h_color}">{h_val:.0%}</td>'
            f'<td style="text-align:center">{shadow_mark}</td>'
            f'<td>{jf:.0%}</td>'
            f'<td>{ec}</td><td>{wc}</td></tr>'
        )
    parts.append('</tbody></table>')
    if collapse:
        parts.append('</details>')

    parts.append('</div></div>')
    return "\n".join(parts)


def _html_config_section(result: "AuditResult") -> str:
    """Build the config/audit context panel HTML."""
    config_snapshot = result.config_snapshot
    if not config_snapshot:
        return ""

    parts: list[str] = []
    parts.append('<div class="section" id="section-config">')
    parts.append('<div class="section-head">Audit Context</div>')
    parts.append('<div class="section-body">')

    parts.append('<table>')
    provider = config_snapshot.get("provider", "—")
    model = config_snapshot.get("model", "—")
    timestamp = config_snapshot.get("timestamp", "—")
    phases = config_snapshot.get("phases_run", [])
    parts.append(f'<tr><td><strong>Provider</strong></td><td>{_h(str(provider))}</td></tr>')
    parts.append(f'<tr><td><strong>Model</strong></td><td>{_h(str(model))}</td></tr>')
    if phases:
        parts.append(f'<tr><td><strong>Phases</strong></td><td>{_h(", ".join(str(p) for p in phases))}</td></tr>')
    parts.append(f'<tr><td><strong>Timestamp</strong></td><td>{_h(str(timestamp))}</td></tr>')
    parts.append('</table>')

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
    if scorecard.enforcement_total_obligations is None:
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


def _html_info_section(result: "AuditResult") -> str:
    """Build the info-level issues section HTML."""
    infos = [i for i in result.issues if i.severity == "info"]
    if not infos:
        return ""

    implicit_contracts = [i for i in infos if i.category == "obligation_implicit_contract"]
    other_infos = [i for i in infos if i.category != "obligation_implicit_contract"]

    parts: list[str] = []

    if other_infos:
        parts.append('<div class="section" id="section-info">')
        parts.append('<div class="section-head">Info</div>')
        parts.append('<div class="section-body">')
        parts.append(f'<p>{len(other_infos)} advisory finding(s)</p>')
        collapse = len(other_infos) > 20
        if collapse:
            parts.append(f'<details><summary>All findings ({len(other_infos)})</summary>')
        parts.append('<ul class="file-list">')
        for issue in other_infos:
            parts.append(f'<li>{_h(str(issue.path))}{_issue_loc(issue)}: {_h(issue.message)}</li>')
        parts.append('</ul>')
        if collapse:
            parts.append('</details>')
        parts.append('</div></div>')

    if implicit_contracts:
        has_test_pairs = any(_is_test_path(str(ic.path)) for ic in implicit_contracts)
        parts.append('<div class="section" id="section-implicit-contracts">')
        parts.append('<div class="section-head">Implicit String Contracts</div>')
        parts.append('<div class="section-body">')
        if has_test_pairs:
            parts.append(f'<p>{_h(_IMPLICIT_CONTRACT_PREAMBLE)}</p>')
        parts.append(f'<p>{len(implicit_contracts)} finding(s)</p>')
        collapse = len(implicit_contracts) > 20
        if collapse:
            parts.append(f'<details><summary>All findings ({len(implicit_contracts)})</summary>')
        parts.append('<ul class="file-list">')
        for issue in implicit_contracts:
            parts.append(f'<li>{_h(str(issue.path))}{_issue_loc(issue)}: {_h(issue.message)}</li>')
        parts.append('</ul>')
        if collapse:
            parts.append('</details>')
        parts.append('</div></div>')

    return "\n".join(parts)


_THEME_TOGGLE_ONCLICK = (
    "var d=document.documentElement,t=d.getAttribute('data-theme')==='dark'?'light':'dark';"
    "d.setAttribute('data-theme',t);"
    "try{localStorage.setItem('osoji-theme',t);}catch(e){}"
)

_BODY_ONLOAD = (
    "try{var t=localStorage.getItem('osoji-theme');"
    "if(t){document.documentElement.setAttribute('data-theme',t);}"
    "else if(window.matchMedia&&window.matchMedia('(prefers-color-scheme:light)').matches)"
    "{document.documentElement.setAttribute('data-theme','light');}"
    "}catch(e){}"
)

_THEME_TOGGLE_BTN = (
    f'<button class="theme-toggle" id="theme-toggle" aria-label="Toggle light/dark mode"'
    f' onclick="{_THEME_TOGGLE_ONCLICK}">'
    '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
    '<circle cx="12" cy="12" r="5"/>'
    '<path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42'
    'M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'
    '</svg>'
    '<svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
    '<path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/>'
    '</svg>'
    '</button>'
)

_GUIDE_HTML = (
    '<div class="guide">'
    '<p class="guide-heading">How to read this report</p>'
    '<p>Osoji flags; you judge. Findings are LLM-generated and will include '
    'false positives. Treat each finding as a prompt for your attention.</p>'
    '</div>'
)


def format_audit_html(result: AuditResult, config: "Config | None" = None) -> str:
    """Format audit result as a self-contained HTML dashboard."""
    scorecard = result.scorecard
    errors = [i for i in result.issues if i.severity == "error"]
    warnings = [i for i in result.issues if i.severity == "warning"]
    infos = [i for i in result.issues if i.severity == "info"]
    passed = result.passed

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en" data-theme="dark"><head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>osojicode — Audit Report</title>')
    parts.append(f'<style>{_AUDIT_CSS}</style>')
    parts.append(f'</head><body onload="{_BODY_ONLOAD}">')

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
        f'{_THEME_TOGGLE_BTN}'
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

        # B6: Obligation metrics card
        if scorecard.obligation_violations is not None:
            obl_color = "green" if scorecard.obligation_violations == 0 else "coral"
            parts.append(_html_metric_card(
                "Obligations", str(scorecard.obligation_violations),
                f"{scorecard.obligation_implicit_contracts} implicit contracts",
                "section-enforcement", obl_color))

        # Doc Gaps metric card
        if result.doc_prompts is not None:
            gap_count = result.doc_prompts.total_gaps
            gap_color = "green" if gap_count == 0 else ("amber" if gap_count < 10 else "coral")
            parts.append(_html_metric_card(
                "Doc Gaps", str(gap_count),
                f"{result.doc_prompts.total_prompts} prompts",
                "section-doc-prompts", gap_color))

        parts.append('</div>')

        # B7: Interpretive guide
        parts.append(_GUIDE_HTML)

        # Load shadow content for coverage matrix previews
        shadow_previews: dict[str, str] | None = None
        if config is not None:
            shadow_previews = {}
            for entry in scorecard.coverage_entries:
                content = load_shadow_content(config, entry.source_path)
                if content:
                    shadow_previews[entry.source_path] = content

        # Sections
        parts.append(_html_coverage_section(scorecard, shadow_content=shadow_previews))
        parts.append(_html_doc_prompts_section(result))
        parts.append(_html_accuracy_section(result))
        parts.append(_html_junk_section(result))
        parts.append(_html_file_health_section(result))
        parts.append(_html_dead_docs_section(scorecard))
        parts.append(_html_enforcement_section(scorecard))
        parts.append(_html_info_section(result))
        parts.append(_html_config_section(result))

    parts.append('</div>')  # container

    # Footer
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(f'<div class="footer">{len(errors)} error(s), {len(warnings)} warning(s), '
                 f'{len(infos)} info(s) &middot; {_h(now)}'
                 f'<br>osojicode</div>')

    parts.append('</body></html>')
    return "\n".join(parts)
