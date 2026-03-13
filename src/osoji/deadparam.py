"""Dead parameter detection: find function parameters no caller ever passes.

Two-phase architecture matching DeadCodeAnalyzer:
  Phase 1 — Candidate scanning (pure Python, no LLM): find exported functions
            with optional parameters that have callers but no call site passes
            those optional params.
  Phase 2 — LLM verification (batched, async): confirm dead params with full
            call-site context and identify gated branches.
"""

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .async_utils import gather_with_buffer
from .config import Config, SHADOW_DIR
from .facts import FactsDB
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult, load_shadow_content, validate_line_ranges
from .llm.base import LLMProvider
from .llm.budgets import input_budget_for_config
from .llm.tokens import estimate_completion_input_tokens_offline
from .llm.types import Message, MessageRole, CompletionOptions
from .symbols import load_all_symbols
from .tools import get_dead_parameter_tool_definitions
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


@dataclass
class DeadParamVerification:
    """Result of verifying whether a parameter is dead."""

    source_path: str
    function_name: str
    param_name: str
    is_dead: bool
    confidence: float
    reason: str
    remediation: str
    param_line: int = 0
    gated_line_ranges: list[tuple[int, int]] = field(default_factory=list)


_MAX_DEFINING_FILE_CHARS = 40_000
_MAX_CALL_SITES_PER_FILE = 5
_MAX_CALL_SITES_PER_REQUEST = 50


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


def _partition_call_sites_by_file(call_sites: list[CallSite]) -> list[list[CallSite]]:
    grouped: dict[str, list[CallSite]] = defaultdict(list)
    for call_site in call_sites:
        grouped[call_site.file_path].append(call_site)

    groups: list[list[CallSite]] = []
    for file_path in sorted(grouped):
        file_sites = sorted(grouped[file_path], key=lambda item: item.line_number)
        for start in range(0, len(file_sites), _MAX_CALL_SITES_PER_FILE):
            groups.append(file_sites[start:start + _MAX_CALL_SITES_PER_FILE])
    return groups


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
            opt_params = [(p["name"], line_start, True) for p in parameters if p.get("optional")]
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


# --- Phase 2: LLM verification ---

_DEAD_PARAM_SYSTEM_PROMPT = """You are a dead parameter analyst. You are given a function with optional parameters, along with a deduplicated chunk of call sites gathered from the codebase.

Your job: determine whether each optional parameter is genuinely dead (never passed by any caller) or alive.

## Rules for judging parameter liveness

A parameter is ALIVE if:
- ANY call site passes it (as a keyword argument, positional argument, or via **kwargs spread)
- It is part of an interface/protocol that subclasses must implement
- The function is a callback whose signature is constrained by a caller
- It is required by an ABC or protocol definition

A parameter is DEAD if:
- No call site passes it AND no dynamic dispatch could provide it
- All callers use the default value (explicitly or implicitly)

## For confirmed dead parameters

Identify conditional branches in the function body that are gated EXCLUSIVELY by the dead parameter. These are branches that would become dead code if the parameter were removed, because they only execute when the parameter differs from its default value.

Examples of gated branches (any language):
- `if param is not None:` / `if (param != null)` / `if param != nil` — the entire if-block is gated
- `if param:` / `if (param)` when default is None/False/0/null
- `elif param is not None:` / `else if (param !== undefined)` — the elif/else-if block is gated
- `param = param if param is not None else fallback` / `param ?? fallback` — the conditional expression

Report the line ranges of these gated branches.

Use the verify_dead_parameters tool with a verdict for EVERY parameter under analysis."""


def _build_deadparam_prompt(
    candidates: list[DeadParamCandidate],
    file_content: str,
    shadow_content: str,
    call_sites: list[CallSite],
    *,
    total_call_sites: int,
) -> str:
    user_parts: list[str] = []
    source_path = candidates[0].source_path
    func_name = candidates[0].function_name

    user_parts.append("## Parameters under analysis\n")
    user_parts.append(f"Function: `{func_name}` in `{source_path}`\n")
    for candidate in candidates:
        default_str = "has default" if candidate.has_default else "no default"
        user_parts.append(
            f"- `{candidate.param_name}` (function defined at line {candidate.param_line}, {default_str})"
        )
    user_parts.append("")

    truncated = file_content[:_MAX_DEFINING_FILE_CHARS]
    if len(file_content) > _MAX_DEFINING_FILE_CHARS:
        truncated += "\n\n[... defining file truncated ...]"
    user_parts.append(f"## Defining file: `{source_path}`\n```\n{truncated}\n```\n")

    if shadow_content:
        user_parts.append(f"## Shadow doc for `{source_path}`\n{shadow_content}\n")

    user_parts.append(
        f"## Call sites in this verification chunk ({len(call_sites)} of {total_call_sites} deduplicated call sites)\n"
    )
    for index, call_site in enumerate(call_sites, 1):
        user_parts.append(
            f"### Call site {index}: `{call_site.file_path}` line {call_site.line_number}\n```\n{call_site.context}\n```\n"
        )

    param_names = ", ".join(f"`{candidate.param_name}`" for candidate in candidates)
    user_parts.append(
        f"Provide a verdict for EVERY parameter listed ({param_names}) "
        "using the verify_dead_parameters tool."
    )
    return "\n".join(user_parts)


def _estimate_deadparam_prompt_tokens(config: Config, user_prompt: str) -> int:
    return estimate_completion_input_tokens_offline(
        [Message(role=MessageRole.USER, content=user_prompt)],
        system=_DEAD_PARAM_SYSTEM_PROMPT,
        tools=get_dead_parameter_tool_definitions(),
        tool_choice={"type": "tool", "name": "verify_dead_parameters"},
    )


def _build_call_site_chunks(
    config: Config,
    candidates: list[DeadParamCandidate],
    file_content: str,
    shadow_content: str,
) -> list[list[CallSite]]:
    all_call_sites = _dedupe_call_sites(candidates[0].call_sites)
    if not all_call_sites:
        return []

    max_input_tokens = input_budget_for_config(config)
    file_groups = _partition_call_sites_by_file(all_call_sites)
    chunks: list[list[CallSite]] = []
    current_chunk: list[CallSite] = []

    for group in file_groups:
        if len(current_chunk) + len(group) > _MAX_CALL_SITES_PER_REQUEST and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []

        proposed_chunk = current_chunk + group
        prompt = _build_deadparam_prompt(
            candidates,
            file_content,
            shadow_content,
            proposed_chunk,
            total_call_sites=len(all_call_sites),
        )
        if current_chunk and _estimate_deadparam_prompt_tokens(config, prompt) > max_input_tokens:
            chunks.append(current_chunk)
            current_chunk = list(group)
            continue

        current_chunk = proposed_chunk

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _merge_verifications(
    candidates: list[DeadParamCandidate],
    chunk_results: list[list[DeadParamVerification]],
) -> list[DeadParamVerification]:
    by_param: dict[str, list[DeadParamVerification]] = defaultdict(list)
    for result in chunk_results:
        for verification in result:
            by_param[verification.param_name].append(verification)

    merged: list[DeadParamVerification] = []
    for candidate in candidates:
        param_results = by_param.get(candidate.param_name, [])
        if not param_results:
            continue

        alive_results = [result for result in param_results if not result.is_dead]
        if alive_results:
            merged.append(max(alive_results, key=lambda item: item.confidence))
            continue

        best_dead = max(param_results, key=lambda item: item.confidence)
        gated_ranges = sorted(
            {
                gated_range
                for result in param_results
                for gated_range in result.gated_line_ranges
            }
        )
        merged.append(
            DeadParamVerification(
                source_path=best_dead.source_path,
                function_name=best_dead.function_name,
                param_name=best_dead.param_name,
                is_dead=True,
                confidence=best_dead.confidence,
                reason=best_dead.reason,
                remediation=best_dead.remediation,
                param_line=best_dead.param_line,
                gated_line_ranges=gated_ranges,
            )
        )

    return merged


async def _verify_chunk_async(
    provider: LLMProvider,
    config: Config,
    candidates: list[DeadParamCandidate],
    file_content: str,
    shadow_content: str,
    *,
    total_call_sites: int,
) -> tuple[list[DeadParamVerification], int, int]:
    """Verify one caller-evidence chunk for a single function."""

    user_prompt = _build_deadparam_prompt(
        candidates,
        file_content,
        shadow_content,
        candidates[0].call_sites,
        total_call_sites=total_call_sites,
    )

    expected_params = {(candidate.function_name, candidate.param_name) for candidate in candidates}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_dead_parameters":
            return []
        verdicts = tool_input.get("verdicts", [])
        got = {(verdict.get("function_name"), verdict.get("parameter_name")) for verdict in verdicts}
        missing = expected_params - got
        return [f"Missing verdict for {fn}.{pn}" for fn, pn in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_DEAD_PARAM_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(1024, len(candidates) * 300),
            max_input_tokens=input_budget_for_config(config),
            reservation_key="deadparam.verify_batch",
            tools=get_dead_parameter_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_dead_parameters"},
            tool_input_validators=[check_completeness, validate_line_ranges],
        ),
    )

    candidate_by_key = {
        (candidate.function_name, candidate.param_name): candidate
        for candidate in candidates
    }
    verifications: list[DeadParamVerification] = []
    for tool_call in result.tool_calls:
        if tool_call.name != "verify_dead_parameters":
            continue
        for verdict in tool_call.input.get("verdicts", []):
            key = (
                verdict.get("function_name", ""),
                verdict.get("parameter_name", ""),
            )
            candidate = candidate_by_key.get(key)
            if candidate is None:
                continue
            gated = [
                (line_range["line_start"], line_range["line_end"])
                for line_range in verdict.get("gated_line_ranges", [])
                if isinstance(line_range, dict)
            ]
            verifications.append(
                DeadParamVerification(
                    source_path=candidate.source_path,
                    function_name=candidate.function_name,
                    param_name=candidate.param_name,
                    is_dead=verdict["is_dead"],
                    confidence=verdict["confidence"],
                    reason=verdict["reason"],
                    remediation=verdict["remediation"],
                    param_line=candidate.param_line,
                    gated_line_ranges=gated,
                )
            )

    if not verifications:
        raise RuntimeError(
            f"LLM did not return verdicts for {candidates[0].function_name} params: "
            f"{[candidate.param_name for candidate in candidates]}"
        )

    return verifications, result.input_tokens, result.output_tokens


async def _verify_batch_async(
    provider: LLMProvider,
    config: Config,
    candidates: list[DeadParamCandidate],
    file_content: str,
    shadow_content: str,
) -> tuple[list[DeadParamVerification], int, int]:
    """Verify one function's parameters, splitting caller evidence across requests."""

    call_site_chunks = _build_call_site_chunks(config, candidates, file_content, shadow_content)
    if not call_site_chunks:
        raise RuntimeError(
            f"No call sites available for {candidates[0].function_name} in {candidates[0].source_path}"
        )

    chunk_results: list[list[DeadParamVerification]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_call_sites = len(_dedupe_call_sites(candidates[0].call_sites))

    for chunk in call_site_chunks:
        chunk_candidates = [
            DeadParamCandidate(
                source_path=candidate.source_path,
                function_name=candidate.function_name,
                param_name=candidate.param_name,
                param_line=candidate.param_line,
                has_default=candidate.has_default,
                call_sites=list(chunk),
            )
            for candidate in candidates
        ]
        verifications, input_tokens, output_tokens = await _verify_chunk_async(
            provider,
            config,
            chunk_candidates,
            file_content,
            shadow_content,
            total_call_sites=total_call_sites,
        )
        chunk_results.append(verifications)
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

    merged = _merge_verifications(candidates, chunk_results)
    if not merged:
        raise RuntimeError(
            f"LLM did not return verdicts for {candidates[0].function_name} params: "
            f"{[candidate.param_name for candidate in candidates]}"
        )

    return merged, total_input_tokens, total_output_tokens


async def detect_dead_params_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DeadParamVerification]:
    """Detect dead parameters across the project with parallel LLM verification.

    Returns all verdicts (dead and alive); caller filters to is_dead=True.
    """
    candidates = scan_dead_param_candidates(config)

    # Group by (source_path, function_name) for batching
    by_func: dict[tuple[str, str], list[DeadParamCandidate]] = {}
    for c in candidates:
        key = (c.source_path, c.function_name)
        by_func.setdefault(key, []).append(c)

    print(
        f"  Found {len(candidates)} optional parameter(s) across "
        f"{len(by_func)} function(s) for LLM verification",
        flush=True,
    )

    if not candidates:
        return []

    # Pre-load file contents and shadow docs
    file_contents: dict[str, str] = {}
    shadow_contents: dict[str, str] = {}

    for c in candidates:
        if c.source_path not in file_contents:
            src_path = config.root_path / c.source_path
            try:
                file_contents[c.source_path] = src_path.read_text(errors="ignore")
            except OSError:
                file_contents[c.source_path] = ""
        if c.source_path not in shadow_contents:
            shadow_contents[c.source_path] = load_shadow_content(config, c.source_path)

    results: list[DeadParamVerification] = []
    batches = list(by_func.values())
    completed_batches = 0
    total_batches = len(batches)
    lock = asyncio.Lock()

    async def process_batch(batch: list[DeadParamCandidate]) -> list[DeadParamVerification]:
        nonlocal completed_batches

        source_path = batch[0].source_path
        try:
            verifications, _in_tok, _out_tok = await _verify_batch_async(
                provider,
                config,
                batch,
                file_contents.get(source_path, ""),
                shadow_contents.get(source_path, ""),
            )
            async with lock:
                completed_batches += 1
                for v in verifications:
                    results.append(v)
                if on_progress:
                    on_progress(
                        completed_batches, total_batches,
                        Path(source_path),
                        f"{sum(1 for v in verifications if v.is_dead)} dead",
                    )
            return verifications
        except Exception as e:
            async with lock:
                completed_batches += 1
                if on_progress:
                    on_progress(
                        completed_batches, total_batches,
                        Path(source_path), "error",
                    )
            func_name = batch[0].function_name
            params = [c.param_name for c in batch]
            print(f"  [error] {source_path}:{func_name}({params}): {e}", flush=True)
            return []

    await gather_with_buffer([lambda batch=batch: process_batch(batch) for batch in batches])

    return results


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
        results = await detect_dead_params_async(provider, config, on_progress)
        findings = []
        for v in results:
            if not v.is_dead:
                continue
            # Compute line range: use gated ranges if available, otherwise param line
            if v.gated_line_ranges:
                line_start = min(r[0] for r in v.gated_line_ranges)
                line_end = max(r[1] for r in v.gated_line_ranges)
            else:
                line_start = v.param_line or 1
                line_end = v.param_line or 1
            findings.append(JunkFinding(
                source_path=v.source_path,
                name=f"{v.function_name}.{v.param_name}",
                kind="parameter",
                category="dead_parameter",
                line_start=line_start,
                line_end=line_end,
                confidence=v.confidence,
                reason=v.reason,
                remediation=v.remediation,
                original_purpose=f"parameter `{v.param_name}` of `{v.function_name}`",
                confidence_source="llm_inferred",
                metadata={
                    "function_name": v.function_name,
                    "gated_lines": [list(r) for r in v.gated_line_ranges],
                },
            ))
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(results),
            analyzer_name=self.name,
        )
