"""Cross-file dead code detection via public symbol reference scanning."""

import asyncio
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .junk import JunkAnalyzer, JunkFinding, JunkAnalysisResult, load_shadow_content, validate_line_ranges
from .llm.base import LLMProvider
from .llm.factory import create_provider
from .llm.logging import LoggingProvider
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter, get_config_with_overrides
from .symbols import load_all_symbols
from .tools import get_dead_code_tool_definitions
from .walker import list_repo_files, _matches_ignore


@dataclass
class GrepHit:
    """A textual reference to a symbol found in another file."""

    file_path: str  # relative path where reference was found
    line_number: int
    context: str  # ±5 lines around the match


@dataclass
class DeadCodeCandidate:
    """A symbol that may be dead code."""

    source_path: str  # relative path to defining file
    name: str  # symbol name
    kind: str  # function/class/constant/variable
    line_start: int
    line_end: int | None
    ref_count: int  # number of external file references
    grep_hits: list[GrepHit] = field(default_factory=list)


@dataclass
class DeadCodeVerification:
    """Result of verifying whether a symbol is dead code."""

    source_path: str
    name: str
    kind: str
    line_start: int
    line_end: int | None
    is_dead: bool
    confidence: float
    reason: str
    remediation: str


def _extract_context(lines: list[str], line_number: int, radius: int = 5) -> str:
    """Extract ±radius lines of context around a match (1-indexed line_number)."""
    idx = line_number - 1  # convert to 0-indexed
    start = max(0, idx - radius)
    end = min(len(lines), idx + radius + 1)
    context_lines = []
    for i in range(start, end):
        marker = ">>>" if i == idx else "   "
        context_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")
    return "\n".join(context_lines)


def scan_references(
    config: Config,
) -> tuple[list[DeadCodeCandidate], list[DeadCodeCandidate]]:
    """Scan for symbols with zero or low external references.

    Returns (zero_ref_candidates, low_ref_candidates).
    Pure Python, no LLM calls.
    """
    all_symbols = load_all_symbols(config)
    if not all_symbols:
        return [], []

    # Collect all unique symbol names
    symbol_names: set[str] = set()
    for symbols in all_symbols.values():
        for sym in symbols:
            symbol_names.add(sym["name"])

    if not symbol_names:
        return [], []

    # Build one compiled regex: \b(sym1|sym2|...)\b
    # Sort longest-first to avoid prefix-match issues in alternation
    sorted_names = sorted(symbol_names, key=len, reverse=True)
    escaped = [re.escape(name) for name in sorted_names]
    pattern = re.compile(r"\b(" + "|".join(escaped) + r")\b")

    # Get ALL repo files
    all_paths, _ = list_repo_files(config)
    all_paths = list(all_paths)

    docstarignore = config.load_docstarignore()

    # For each file, find which symbol names appear and at which lines
    # file_refs[symbol_name] = {relative_file_path: [line_numbers]}
    file_refs: dict[str, dict[str, list[int]]] = {name: {} for name in symbol_names}

    # Also cache file lines for context extraction
    file_lines_cache: dict[str, list[str]] = {}

    for path in all_paths:
        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)
        # Normalize to forward slashes
        rel_str = str(relative).replace("\\", "/")

        # Skip .docstar/
        if rel_str.startswith(".docstar"):
            continue

        # Skip ignore patterns
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if docstarignore and _matches_ignore(relative, docstarignore):
            continue

        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue

        # Find all matches
        matches_in_file: dict[str, list[int]] = {}
        lines = content.split("\n")
        for line_idx, line in enumerate(lines):
            for m in pattern.finditer(line):
                name = m.group(1)
                if name not in matches_in_file:
                    matches_in_file[name] = []
                matches_in_file[name].append(line_idx + 1)  # 1-indexed

        for name, line_numbers in matches_in_file.items():
            file_refs[name][rel_str] = line_numbers

        # Cache lines if any symbols were found
        if matches_in_file:
            file_lines_cache[rel_str] = lines

    # For each symbol, count external files
    zero_ref: list[DeadCodeCandidate] = []
    low_ref: list[DeadCodeCandidate] = []

    # Build per-symbol external ref counts
    sym_ref_counts: dict[tuple[str, str], int] = {}  # (source_path, name) -> count
    sym_entries: list[tuple[str, dict]] = []  # (source_path, symbol_dict)

    for source_path, symbols in all_symbols.items():
        # Normalize source path
        source_norm = source_path.replace("\\", "/")
        for sym in symbols:
            name = sym["name"]
            refs = file_refs.get(name, {})
            # Count files other than the defining file
            external_count = sum(
                1 for f in refs if f != source_norm
            )
            sym_ref_counts[(source_norm, name)] = external_count
            sym_entries.append((source_norm, sym))

    # --- Transitive liveness: filter out zero-ref symbols that are used
    #     within the same file by symbols with external refs > 0 ---
    # A symbol is transitively alive if it is referenced within its own file
    # by another symbol that has external refs > 0 (or is itself transitively alive).

    # Build per-file symbol data
    file_sym_data: dict[str, list[tuple[str, int, int | None]]] = {}
    for source_norm, sym in sym_entries:
        file_sym_data.setdefault(source_norm, []).append(
            (sym["name"], sym["line_start"], sym.get("line_end"))
        )

    # Only process files that have at least one zero-ref candidate
    zero_ref_files = {
        sn
        for (sn, _name), count in sym_ref_counts.items()
        if count == 0
    }

    transitively_alive: set[tuple[str, str]] = set()  # (file, name)

    for fpath in zero_ref_files:
        symbols_in_file = file_sym_data.get(fpath)
        if not symbols_in_file or len(symbols_in_file) < 2:
            continue

        cached_lines = file_lines_cache.get(fpath)
        if not cached_lines:
            continue

        # Build regex for just this file's symbols
        sym_names_in_file = {s[0] for s in symbols_in_file}
        sorted_file_names = sorted(sym_names_in_file, key=len, reverse=True)
        file_pattern = re.compile(
            r"\b(" + "|".join(re.escape(n) for n in sorted_file_names) + r")\b"
        )

        # Build within-file reference graph: uses[A] = {B, C} means A's body
        # contains references to symbols B and C
        uses: dict[str, set[str]] = {s[0]: set() for s in symbols_in_file}

        for sym_name, line_start, line_end in symbols_in_file:
            start_idx = line_start - 1  # 0-indexed
            end_idx = line_end if line_end else line_start  # 1-indexed inclusive

            for line_idx in range(start_idx, min(end_idx, len(cached_lines))):
                for m in file_pattern.finditer(cached_lines[line_idx]):
                    referenced = m.group(1)
                    if referenced != sym_name:
                        uses[sym_name].add(referenced)

        # Seeds: symbols with external refs > 0
        alive: set[str] = set()
        for sym_name, _, _ in symbols_in_file:
            if sym_ref_counts.get((fpath, sym_name), 0) > 0:
                alive.add(sym_name)

        # BFS propagation: if alive symbol uses another, that symbol is alive too
        queue = list(alive)
        while queue:
            current = queue.pop()
            for referenced in uses.get(current, set()):
                if referenced not in alive:
                    alive.add(referenced)
                    queue.append(referenced)

        # Record zero-ref symbols that are transitively alive
        for sym_name in alive:
            if sym_ref_counts.get((fpath, sym_name), 0) == 0:
                transitively_alive.add((fpath, sym_name))

    # Compute 10th percentile of non-zero reference counts
    non_zero_counts = [c for c in sym_ref_counts.values() if c > 0]
    if non_zero_counts:
        sorted_counts = sorted(non_zero_counts)
        p10_index = max(0, math.ceil(len(sorted_counts) * 0.10) - 1)
        threshold = sorted_counts[p10_index]
        threshold = min(threshold, 10)  # Cap at 10
    else:
        threshold = 0

    for source_norm, sym in sym_entries:
        name = sym["name"]
        # Internal symbols are not dead code candidates
        if sym.get("visibility") == "internal":
            continue
        ext_count = sym_ref_counts[(source_norm, name)]

        if ext_count == 0:
            if (source_norm, name) in transitively_alive:
                continue  # Skip — transitively alive via within-file usage
            zero_ref.append(DeadCodeCandidate(
                source_path=source_norm,
                name=name,
                kind=sym["kind"],
                line_start=sym["line_start"],
                line_end=sym.get("line_end"),
                ref_count=0,
            ))
        elif ext_count <= threshold:
            # Build GrepHit objects
            refs = file_refs.get(name, {})
            grep_hits: list[GrepHit] = []
            for ref_file, line_numbers in refs.items():
                if ref_file == source_norm:
                    continue
                cached_lines = file_lines_cache.get(ref_file)
                if not cached_lines:
                    continue
                for ln in line_numbers:
                    context = _extract_context(cached_lines, ln)
                    grep_hits.append(GrepHit(
                        file_path=ref_file,
                        line_number=ln,
                        context=context,
                    ))
            low_ref.append(DeadCodeCandidate(
                source_path=source_norm,
                name=name,
                kind=sym["kind"],
                line_start=sym["line_start"],
                line_end=sym.get("line_end"),
                ref_count=ext_count,
                grep_hits=grep_hits,
            ))

    return zero_ref, low_ref


# --- LLM verification ---

_DEAD_CODE_SYSTEM_PROMPT = """You are a dead code analyst. You are given one or more symbols from the same file, along with context about where (if anywhere) each is referenced across the codebase.

Your job: determine whether each symbol is genuinely dead code or alive. Provide a verdict for EVERY symbol listed.

## For zero-reference symbols (no external textual references found)
The symbol has NO grep hits outside its defining file. But it may still be alive:
- Decorators / framework magic (@app.route, @pytest.fixture, @property, signal handlers)
- Convention-based dispatch (Django views, Flask endpoints, Click commands, test_ methods)
- Dynamic dispatch (getattr(), importlib, plugin registries, __getattr__)
- Dunder / magic methods (__init__, __str__, __enter__, __eq__) — called implicitly
- Explicit public API exports (Python: __all__, __init__.py re-exports; JS/TS: export in
  barrel files; Rust: pub use re-exports; Go: capitalized identifiers)
- Visibility-based liveness (Rust: pub fn/pub struct; Java/C#: public methods; Go: capitalized
  names) — BUT only when the containing crate/package is a library consumed externally
- Entry points (console_scripts in pyproject.toml/setup.py, main() functions, bin scripts)
- Callbacks / hooks registered at runtime
- Overrides of abstract methods or interface conformance
- Trait implementations (Rust: impl Trait for Type — invoked implicitly, no direct call site)
- #[derive], #[no_mangle], extern "C", FFI exports — used by generated code or foreign callers
- Within-file transitive liveness: a symbol is alive if an externally-referenced symbol
  in the SAME file directly or indirectly USES it — even through chains of private helper
  functions (e.g. a constant used inside a private function that is called by a public
  function; a dataclass returned by an exported API). The liveness flows FROM the
  externally-referenced entry point INTO what it calls/uses — a sibling function that
  merely references the same constant is NOT alive through this path.

## Decision rule for zero-reference symbols
If a zero-reference symbol does not match ANY of the liveness patterns above, it IS dead code.
Do not invent other reasons to keep it alive. Specifically:
- "It could be used by external consumers" is NOT a valid reason unless the symbol is
  explicitly exported (Python: __all__ / __init__.py; JS/TS: export; Rust: pub use; etc.)
- "It wraps a symbol that is used" is NOT a valid reason — if the wrapper itself has zero
  references, it's dead regardless of what it wraps. Example: get_foo_tools() returns
  [FOO_TOOL] and get_foo_tool_definitions() also returns FOO_TOOL; if only the latter is
  imported, the former is dead even though they share the same constant
- "It might be part of the public API" is NOT valid without an explicit export mechanism
- "It returns something that is used" is NOT valid — the function must itself be called
- "It looks like framework/orchestration code" is NOT valid — if a function has zero
  references, it is not being called by any framework regardless of what it returns
- "It is used within the same file" IS a valid reason IF an externally-referenced symbol
  directly or indirectly uses it — even through chains of private/internal functions

## For low-reference symbols (few external grep hits)
Each grep hit has ±5 lines of context. Judge whether each hit is a real usage or a false positive:
- **Comment / docstring**: mentioned in a comment but never actually called
- **String literal**: appears in a log message, error string, or config key
- **Name collision**: a different module defines a symbol with the same name
- **Type annotation only**: used in a type hint but never called at runtime

If ALL hits are false positives, the symbol is dead.
If ANY hit is a real usage (import, call, attribute access), the symbol is alive.

Use the verify_dead_code tool with a verdict for EVERY symbol."""


async def _verify_batch_async(
    provider: LLMProvider,
    config: Config,
    candidates: list[DeadCodeCandidate],
    file_content: str,
    shadow_content: str,
    ref_shadow_contents: dict[str, str],
) -> tuple[list[DeadCodeVerification], int, int]:
    """Verify a batch of dead code candidates (all from the same defining file) via one LLM call.

    Returns (list[DeadCodeVerification], input_tokens, output_tokens).
    """
    user_parts: list[str] = []

    # List all symbols in the batch
    user_parts.append("## Symbols under analysis\n")
    for candidate in candidates:
        lines_str = str(candidate.line_start) + (f"-{candidate.line_end}" if candidate.line_end else "")
        user_parts.append(
            f"- `{candidate.name}` ({candidate.kind}, lines {lines_str}, "
            f"external refs: {candidate.ref_count})"
        )
    user_parts.append("")

    # Include defining file content ONCE (truncated)
    source_path = candidates[0].source_path
    truncated = file_content[:100000] if len(file_content) > 100000 else file_content
    user_parts.append(f"## Defining file: `{source_path}`\n```\n{truncated}\n```\n")

    # Include shadow doc for defining file ONCE
    if shadow_content:
        user_parts.append(f"## Shadow doc for `{source_path}`\n{shadow_content}\n")

    # Include grep hits per symbol (only for candidates that have them)
    has_hits = [c for c in candidates if c.grep_hits]
    if has_hits:
        user_parts.append("## Grep hits by symbol\n")
        for candidate in has_hits:
            user_parts.append(f"### `{candidate.name}` ({len(candidate.grep_hits)} references)\n")
            for i, hit in enumerate(candidate.grep_hits, 1):
                user_parts.append(f"#### Hit {i}: `{hit.file_path}` line {hit.line_number}\n```\n{hit.context}\n```\n")
                ref_shadow = ref_shadow_contents.get(hit.file_path, "")
                if ref_shadow:
                    user_parts.append(f"Shadow doc for `{hit.file_path}`:\n{ref_shadow}\n")

    names_list = ", ".join(f"`{c.name}`" for c in candidates)
    user_parts.append(
        f"Provide a verdict for EVERY symbol listed ({names_list}) "
        "using the verify_dead_code tool."
    )

    # Build completeness validator
    expected_names = {c.name for c in candidates}

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_dead_code":
            return []
        verdicts = tool_input.get("verdicts", [])
        got_names = {v.get("symbol_name") for v in verdicts}
        missing = expected_names - got_names
        return [f"Missing verdict for symbol '{name}'" for name in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_DEAD_CODE_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model,
            max_tokens=max(1024, len(candidates) * 250),
            tools=get_dead_code_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_dead_code"},
            tool_input_validators=[check_completeness, validate_line_ranges],
        ),
    )

    # Build lookup from candidates for metadata
    candidate_by_name = {c.name: c for c in candidates}

    verifications: list[DeadCodeVerification] = []
    for tool_call in result.tool_calls:
        if tool_call.name == "verify_dead_code":
            for verdict in tool_call.input.get("verdicts", []):
                sym_name = verdict.get("symbol_name", "")
                cand = candidate_by_name.get(sym_name)
                if cand:
                    verifications.append(DeadCodeVerification(
                        source_path=cand.source_path,
                        name=cand.name,
                        kind=cand.kind,
                        line_start=cand.line_start,
                        line_end=cand.line_end,
                        is_dead=verdict["is_dead"],
                        confidence=verdict["confidence"],
                        reason=verdict["reason"],
                        remediation=verdict["remediation"],
                    ))

    if not verifications:
        raise RuntimeError(
            f"LLM did not return verdicts for batch: "
            f"{[c.name for c in candidates]}"
        )

    return verifications, result.input_tokens, result.output_tokens


def _load_shadow_content(config: Config, relative_path: str) -> str:
    """Load shadow doc content for a relative source path."""
    return load_shadow_content(config, relative_path)


async def detect_dead_code_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DeadCodeVerification]:
    """Detect dead code across the project with parallel LLM verification.

    Args:
        provider: LLM provider for API calls
        rate_limiter: Rate limiter for API throttling
        config: Docstar configuration
        on_progress: Optional callback (completed, total, path, status)

    Returns:
        List of verified dead code items (both tiers).
    """
    zero_refs, low_refs = scan_references(config)

    all_candidates = zero_refs + low_refs

    print(
        f"  Found {len(zero_refs)} zero-reference symbol(s), "
        f"{len(low_refs)} low-reference candidate(s) "
        f"({len(all_candidates)} total for LLM verification)",
        flush=True,
    )

    if not all_candidates:
        return []

    results: list[DeadCodeVerification] = []

    # Pre-load file contents and shadow docs for ALL candidates
    file_contents: dict[str, str] = {}
    shadow_contents: dict[str, str] = {}

    for candidate in all_candidates:
        if candidate.source_path not in file_contents:
            src_path = config.root_path / candidate.source_path
            try:
                file_contents[candidate.source_path] = src_path.read_text(errors="ignore")
            except OSError:
                file_contents[candidate.source_path] = ""
        if candidate.source_path not in shadow_contents:
            shadow_contents[candidate.source_path] = _load_shadow_content(
                config, candidate.source_path
            )
        for hit in candidate.grep_hits:
            if hit.file_path not in shadow_contents:
                shadow_contents[hit.file_path] = _load_shadow_content(
                    config, hit.file_path
                )

    # Group candidates by defining file
    by_file: dict[str, list[DeadCodeCandidate]] = {}
    for candidate in all_candidates:
        by_file.setdefault(candidate.source_path, []).append(candidate)

    # Split file groups into batches
    MAX_SYMBOLS_PER_BATCH = 10
    MAX_EXTERNAL_FILES_PER_BATCH = 10

    batches: list[list[DeadCodeCandidate]] = []
    for _source_path, file_candidates in by_file.items():
        current_batch: list[DeadCodeCandidate] = []
        current_ext_files: set[str] = set()

        for candidate in file_candidates:
            cand_ext_files = {hit.file_path for hit in candidate.grep_hits}

            would_exceed_symbols = len(current_batch) + 1 > MAX_SYMBOLS_PER_BATCH
            would_exceed_files = (
                len(current_ext_files | cand_ext_files) > MAX_EXTERNAL_FILES_PER_BATCH
                and candidate.grep_hits
            )

            if current_batch and (would_exceed_symbols or would_exceed_files):
                batches.append(current_batch)
                current_batch = []
                current_ext_files = set()

            current_batch.append(candidate)
            current_ext_files |= cand_ext_files

        if current_batch:
            batches.append(current_batch)

    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed_batches = 0
    total_batches = len(batches)
    lock = asyncio.Lock()

    async def process_batch(batch: list[DeadCodeCandidate]) -> list[DeadCodeVerification]:
        nonlocal completed_batches

        source_path = batch[0].source_path
        async with semaphore:
            await rate_limiter.throttle()
            try:
                # Collect ref shadow docs for all candidates in batch
                ref_shadows: dict[str, str] = {}
                for candidate in batch:
                    for hit in candidate.grep_hits:
                        if hit.file_path not in ref_shadows:
                            ref_shadows[hit.file_path] = shadow_contents.get(hit.file_path, "")

                verifications, verify_in, verify_out = await _verify_batch_async(
                    provider,
                    config,
                    batch,
                    file_contents.get(source_path, ""),
                    shadow_contents.get(source_path, ""),
                    ref_shadows,
                )
                rate_limiter.record_usage(input_tokens=verify_in, output_tokens=verify_out)
                async with lock:
                    completed_batches += 1
                    for v in verifications:
                        if v.is_dead:
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
                names = [c.name for c in batch]
                print(f"  [error] {source_path}:{names}: {e}", flush=True)
                return []

    tasks = [process_batch(b) for b in batches]
    await asyncio.gather(*tasks)

    return results


class DeadCodeAnalyzer(JunkAnalyzer):
    """Junk analyzer that detects cross-file dead code (unused symbols)."""

    @property
    def name(self) -> str:
        return "dead_code"

    @property
    def description(self) -> str:
        return "Detect cross-file dead code (unused symbols)"

    @property
    def cli_flag(self) -> str:
        return "dead-code"

    async def analyze_async(self, provider, rate_limiter, config, on_progress=None):
        results = await detect_dead_code_async(provider, rate_limiter, config, on_progress)
        findings = [
            JunkFinding(
                source_path=v.source_path,
                name=v.name,
                kind=v.kind,
                category="dead_symbol",
                line_start=v.line_start,
                line_end=v.line_end,
                confidence=v.confidence,
                reason=v.reason,
                remediation=v.remediation,
                original_purpose=f"{v.kind} `{v.name}`",
            )
            for v in results if v.is_dead
        ]
        return JunkAnalysisResult(
            findings=findings,
            total_candidates=len(results),
            analyzer_name=self.name,
        )
