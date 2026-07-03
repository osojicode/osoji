"""Dead parameter detection: find function parameters no caller ever passes.

Two-phase architecture matching DeadCodeAnalyzer:
  Phase 1 — Candidate scanning (pure Python, no LLM): find exported functions
            with optional parameters that have callers but no call site passes
            those optional params.
  Phase 2 — Unified verification (V1-5a, spec 0001 step 5): candidates become
            reachability Findings; the Claim Builder gathers call-site and
            cross-file evidence; Triage decides each claim under the unified
            rubric. This module no longer owns an LLM prompt or tool schema.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config, SHADOW_DIR
from .evidence_builders import BuildContext, _scanner_meta
from .facts import FactsDB
from .findings import Finding
from .findings_adapter import finding_from_dead_param_candidate
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult
from .junk_triage import build_junk_claims, decide_junk_claims
from .llm.base import LLMProvider
from .symbols import load_all_symbols
from .walker import list_repo_files, _matches_ignore




# --- Data types ---

@dataclass
class CallSite:
    """A call site for a function found via grep."""

    file_path: str  # relative path
    line_number: int
    context: str  # ±10 lines around the call


@dataclass
class DeadParamCandidate:
    """A function parameter that may be dead (never passed by any caller)."""

    source_path: str  # relative path to defining file
    function_name: str
    param_name: str
    param_line: int  # line of the function definition (symbols lack per-parameter lines)
    has_default: bool  # whether it has a default value
    call_sites: list[CallSite] = field(default_factory=list)


# --- Phase 1: Candidate scanning (pure Python) ---


def _extract_context(lines: list[str], line_number: int, radius: int = 10) -> str:
    """Extract ±radius lines of context around a match (1-indexed line_number)."""
    idx = line_number - 1  # convert to 0-indexed
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    context_lines = []
    for i in range(start, end):
        marker = ">>>" if i == idx else "   "
        context_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")
    return "\n".join(context_lines)


def _dedupe_call_sites(call_sites: list[CallSite]) -> list[CallSite]:
    seen: set[tuple[str, int, str]] = set()
    deduped: list[CallSite] = []
    for call_site in sorted(call_sites, key=lambda item: (item.file_path, item.line_number, item.context)):
        key = (call_site.file_path, call_site.line_number, call_site.context)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call_site)
    return deduped


def scan_dead_param_candidates(
    config: Config,
) -> list[DeadParamCandidate]:
    """Scan for functions with optional parameters that no caller passes.

    Phase 1: Pure Python, no LLM calls.

    Returns list of DeadParamCandidate (one per function+param pair).
    """
    all_symbols = load_all_symbols(config)
    if not all_symbols:
        return []

    # Load facts DB for call information
    facts_db = FactsDB(config)

    # Collect all functions with their callers
    candidates: list[DeadParamCandidate] = []

    # Get all repo files for grep scanning
    all_paths, _ = list_repo_files(config)
    all_paths = list(all_paths)
    osojiignore = config.load_osojiignore()
    repo_files: dict[str, Path] = {}
    for path in all_paths:
        abs_path = path if path.is_absolute() else config.root_path / path
        if not abs_path.is_file():
            continue
        relative = abs_path.relative_to(config.root_path)
        rel_str = str(relative).replace("\\", "/")
        repo_files[rel_str] = abs_path

    # Cache file contents
    file_lines_cache: dict[str, list[str]] = {}

    for source_path, symbols in all_symbols.items():
        source_norm = source_path.replace("\\", "/")

        # Filter to functions only
        functions = [s for s in symbols if s["kind"] == "function"]
        if not functions:
            continue

        # Build class-for-method map using line-range containment
        classes = [s for s in symbols if s["kind"] == "class"]
        class_for_method: dict[str, str] = {}
        for func_sym in functions:
            fl = func_sym["line_start"]
            for cls in classes:
                cls_start = cls["line_start"]
                cls_end = cls.get("line_end", cls_start)
                if cls_start <= fl <= cls_end:
                    class_for_method[func_sym["name"]] = cls["name"]
                    break

        # Read source file
        src_file = config.root_path / source_path
        if not src_file.is_file():
            continue
        try:
            content = src_file.read_text(errors="ignore")
        except OSError:
            continue
        source_lines = content.split("\n")
        file_lines_cache[source_norm] = source_lines

        for sym in functions:
            # Skip internal/private functions
            if sym.get("visibility") == "internal":
                continue

            func_name = sym["name"]
            line_start = sym["line_start"]

            # Check if function has optional parameters (from symbols data)
            parameters = sym.get("parameters", [])
            opt_params = [(p["name"], line_start, p.get("has_default", True)) for p in parameters if p.get("optional")]
            if not opt_params:
                continue

            # Check if function has callers (via facts DB calls or importers)
            # We need at least one caller for this to be interesting —
            # if no one calls it at all, it's a dead symbol (handled by deadcode.py)
            importers = facts_db.importers_of(source_norm)
            if not importers:
                continue

            # Grep for call sites in plausible caller files only
            # For dotted names (e.g. "ClassName.method"), use just the method name
            # so instance calls like `obj.method(` are matched
            grep_name = func_name.rsplit(".", 1)[-1] if "." in func_name else func_name
            call_patterns = [re.compile(r"\b" + re.escape(grep_name) + r"\s*\(")]
            # For constructors nested inside a class, also grep for ClassName(
            parent_class = class_for_method.get(func_name)
            if parent_class:
                call_patterns.append(re.compile(r"\b" + re.escape(parent_class) + r"\s*\("))
            call_sites: list[CallSite] = []

            # Definition range for same-file filtering
            func_def_start = sym["line_start"]
            func_def_end = sym.get("line_end", func_def_start)

            candidate_paths = [source_norm]
            candidate_paths.extend(sorted(set(importers)))

            for rel_str in candidate_paths:
                path = repo_files.get(rel_str, config.root_path / rel_str)
                if not path.is_file():
                    continue

                relative = path.relative_to(config.root_path)

                if rel_str.startswith(SHADOW_DIR):
                    continue
                if _matches_ignore(relative, config.ignore_patterns):
                    continue
                if osojiignore and _matches_ignore(relative, osojiignore):
                    continue
                if config.is_doc_candidate(relative):
                    continue

                is_defining_file = rel_str == source_norm

                # Read file (with caching)
                if rel_str in file_lines_cache:
                    lines = file_lines_cache[rel_str]
                else:
                    try:
                        file_content = path.read_text(errors="ignore")
                    except OSError:
                        continue
                    lines = file_content.split("\n")
                    file_lines_cache[rel_str] = lines

                for line_idx, line in enumerate(lines):
                    if any(p.search(line) for p in call_patterns):
                        line_num = line_idx + 1
                        # In defining file, skip matches inside the function's own body
                        if is_defining_file and func_def_start <= line_num <= func_def_end:
                            continue
                        context = _extract_context(lines, line_num)
                        call_sites.append(CallSite(
                            file_path=rel_str,
                            line_number=line_num,
                            context=context,
                        ))

            call_sites = _dedupe_call_sites(call_sites)
            if not call_sites:
                continue

            # Create a candidate for each optional parameter
            for param_name, param_line, has_default in opt_params:
                candidates.append(DeadParamCandidate(
                    source_path=source_norm,
                    function_name=func_name,
                    param_name=param_name,
                    param_line=param_line,
                    has_default=has_default,
                    call_sites=call_sites,
                ))

    return candidates


# --- Phase 2: Unified verification (Claim Builder + Triage) ---


async def detect_dead_params_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[Finding]:
    """Detect dead parameters through the unified Claim Builder + Triage pipeline.

    The scanner's candidates become reachability Findings whose scan needles
    are the *function's* grep names (never the bare parameter name); the Claim
    Builder's repo sweep re-derives call-site contexts with word-boundary and
    priority-path hygiene, and Triage judges whether any caller passes the
    parameter.

    Returns all decided Findings (every verdict); callers keep ``confirmed``.
    """
    candidates = scan_dead_param_candidates(config)

    by_func: dict[tuple[str, str], list[DeadParamCandidate]] = {}
    for c in candidates:
        by_func.setdefault((c.source_path, c.function_name), []).append(c)

    print(
        f"  Found {len(candidates)} optional parameter(s) across "
        f"{len(by_func)} function(s) for Triage",
        flush=True,
    )

    if not candidates:
        return []

    facts_db = FactsDB(config)
    importers_cache: dict[str, list[str]] = {}

    def importers_of(source_path: str) -> list[str]:
        norm = source_path.replace("\\", "/")
        if norm not in importers_cache:
            importers_cache[norm] = sorted(facts_db.importers_of(norm))
        return importers_cache[norm]

    findings = [
        finding_from_dead_param_candidate(c, importers=importers_of(c.source_path))
        for c in candidates
    ]
    ctx = BuildContext(config, facts_db=facts_db)
    claims = build_junk_claims(findings, ctx)
    decided, _in_tokens, _out_tokens = await decide_junk_claims(
        claims, config, provider, on_progress=on_progress
    )
    return decided


class DeadParameterAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects dead function parameters (never passed by any caller)."""

    @property
    def name(self) -> str:
        return "dead_params"

    @property
    def description(self) -> str:
        return "Detect dead function parameters (never passed by callers)"

    @property
    def cli_flag(self) -> str:
        return "dead-params"

    async def analyze_async(self, provider, config, on_progress=None):
        decided = await detect_dead_params_async(provider, config, on_progress)
        findings = []
        for f in decided:
            if f.verdict != "confirmed":
                continue
            meta = _scanner_meta(f)
            function_name = meta.get("function_name", "")
            param_name = meta.get("param_name", "")
            param_line = f.line_start or 1
            findings.append(JunkFinding(
                source_path=f.path,
                name=f.symbol or f"{function_name}.{param_name}",
                kind="parameter",
                category="dead_parameter",
                line_start=param_line,
                line_end=param_line,
                confidence=f.confidence if f.confidence is not None else 0.0,
                reason=f.triage_reasoning or "",
                remediation=f.suggested_fix or (
                    f"Remove parameter `{param_name}` from `{function_name}`"
                ),
                original_purpose=f"parameter `{param_name}` of `{function_name}`",
                confidence_source="llm_inferred",
                # gated_lines died with the per-detector verify tool: the
                # unified verdict schema carries no detector-specific fields.
                metadata={"function_name": function_name, "gated_lines": []},
            ))
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(decided),
            analyzer_name=self.name,
        )
