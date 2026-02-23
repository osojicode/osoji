"""Core shadow documentation generation orchestration."""

from __future__ import annotations

import asyncio
import errno
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import Config
from .hasher import add_line_numbers, compute_children_hash, compute_file_hash, extract_children_hash, extract_source_hash
from .llm import (
    create_provider,
    LLMProvider,
    LoggingProvider,
    Message,
    MessageRole,
    CompletionOptions,
    CompletionResult,
)
from .rate_limiter import RateLimiter, get_config_with_overrides
from .tools import get_file_tool_definitions, get_directory_tool_definitions
from .walker import (
    discover_files,
    discover_directories,
    get_direct_children,
    get_child_directories,
)


@dataclass
class Finding:
    """A code debris finding from shadow generation."""

    category: str
    line_start: int
    line_end: int
    severity: str  # "error" or "warning"
    description: str
    suggestion: str | None = None


@dataclass
class ShadowResult:
    """Result from processing a single file."""

    path: Path
    body: str
    cached: bool
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    findings: list[Finding] = field(default_factory=list)
    public_symbols: list[dict] = field(default_factory=list)


def assemble_shadow_doc(file_path: Path, source_hash: str, body: str) -> str:
    """Assemble a complete shadow doc with header."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"# {file_path}\n@source-hash: {source_hash}\n@generated: {timestamp}\n\n"
    return header + body


def assemble_directory_shadow_doc(dir_path: Path, children_hash: str, body: str) -> str:
    """Assemble a complete directory shadow doc with header."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"# {dir_path}/\n@children-hash: {children_hash}\n@generated: {timestamp}\n\n"
    return header + body


_TRANSIENT_ERRNOS = {errno.EINVAL, errno.EIO}
_RETRY_DELAYS = [0.5, 1.0, 2.0]


async def _write_with_retry(path: Path, content: str) -> None:
    """Write text to a file, retrying on transient OS errors (e.g. DrvFs/EINVAL)."""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            path.write_text(content, encoding="utf-8")
            return
        except OSError as exc:
            if exc.errno not in _TRANSIENT_ERRNOS or attempt >= len(_RETRY_DELAYS):
                raise
            await asyncio.sleep(_RETRY_DELAYS[attempt])


def is_stale(config: Config, source_path: Path) -> bool:
    """Check if a shadow doc needs regeneration.

    Returns True if:
    - Shadow doc doesn't exist
    - Source hash doesn't match
    - Force flag is set
    """
    if config.force:
        return True

    shadow_path = config.shadow_path_for(source_path)
    if not shadow_path.exists():
        return True

    try:
        shadow_content = shadow_path.read_text(encoding="utf-8")
        cached_hash = extract_source_hash(shadow_content)
        if cached_hash is None:
            return True

        current_hash = compute_file_hash(source_path)
        return cached_hash != current_hash
    except Exception:
        return True


def _extract_body_from_shadow(shadow_content: str) -> str:
    """Extract the body from a shadow doc (skip header)."""
    lines = shadow_content.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        if line == "" and i > 0:
            body_start = i + 1
            break
    return "\n".join(lines[body_start:])


def is_directory_stale(config: Config, dir_path: Path, current_children_hash: str) -> bool:
    """Check if a directory shadow doc needs regeneration.

    Returns True if:
    - Force flag is set
    - Shadow doc doesn't exist
    - Children hash doesn't match (any subtree change)
    - Old format without @children-hash header
    """
    if config.force:
        return True

    shadow_path = config.shadow_path_for_dir(dir_path)
    if not shadow_path.exists():
        return True

    try:
        shadow_content = shadow_path.read_text(encoding="utf-8")
        cached_hash = extract_children_hash(shadow_content)
        if cached_hash is None:
            return True
        return current_children_hash != cached_hash
    except Exception:
        return True


async def generate_file_shadow_doc_async(
    provider: LLMProvider,
    config: Config,
    file_path: Path,
    numbered_content: str,
) -> tuple[str, int, int, list[Finding], list[dict]]:
    """Generate a shadow doc for a single file asynchronously.

    Uses tool_choice to force the LLM to call submit_shadow_doc.
    Returns tuple of (content, input_tokens, output_tokens, findings, public_symbols).
    """
    relative_path = file_path.relative_to(config.root_path)

    system_prompt = """You are a documentation expert generating shadow documentation for AI agent consumption.

Shadow docs are semantically dense summaries that help AI agents quickly understand code.

You MUST use the submit_shadow_doc tool to submit your documentation.
Do not include any header or metadata - just the documentation body.

ALSO: While analyzing the code, identify any "debris" that could mislead an AI coding agent:
- Stale comments that describe behavior the code no longer exhibits
- Misleading docstrings that don't match the actual implementation
- Commented-out code blocks (3+ lines) that agents might reference
- Expired TODO/FIXME comments whose context no longer applies
- Dead code (unreachable branches, unused functions defined but never called within this file)

Report these as findings in the tool call. If the code is clean, submit an empty findings array.

ALSO: Populate the public_symbols array with every function, class, constant, or module-level variable
that other files could import from this module. Include the symbol name, kind, and line range.
Exclude private/underscore-prefixed names UNLESS they are clearly part of the module's cross-file API."""

    user_prompt = f"""Generate shadow documentation for the following file:

**File:** {relative_path}

```
{numbered_content}
```

Analyze this code and submit a shadow doc using the submit_shadow_doc tool.
Include line number references for key elements (e.g., "MyClass (L15-45)").
"""

    messages = [Message(role=MessageRole.USER, content=user_prompt)]
    options = CompletionOptions(
        model=config.model,
        max_tokens=4096,
        tools=get_file_tool_definitions(),
        tool_choice={"type": "tool", "name": "submit_shadow_doc"},
    )

    result = await provider.complete(messages, system_prompt, options)

    for tool_call in result.tool_calls:
        if tool_call.name == "submit_shadow_doc":
            findings_data = tool_call.input.get("findings", [])
            findings = [
                Finding(
                    category=f["category"],
                    line_start=f["line_start"],
                    line_end=f["line_end"],
                    severity=f["severity"],
                    description=f["description"],
                    suggestion=f.get("suggestion"),
                )
                for f in findings_data
            ]
            public_symbols = tool_call.input.get("public_symbols", [])
            return (tool_call.input["content"], result.input_tokens, result.output_tokens, findings, public_symbols)

    raise RuntimeError(f"LLM did not call submit_shadow_doc tool for {file_path}")


async def generate_directory_shadow_doc_async(
    provider: LLMProvider,
    config: Config,
    dir_path: Path,
    child_summaries: list[tuple[Path, str]],
) -> tuple[str, int, int]:
    """Generate a roll-up shadow doc for a directory asynchronously.

    Uses tool_choice to force the LLM to call submit_directory_shadow_doc.
    Returns tuple of (content, input_tokens, output_tokens).
    """
    relative_path = dir_path.relative_to(config.root_path)
    if relative_path == Path("."):
        relative_path = Path("(root)")

    system_prompt = """You are a documentation expert generating shadow documentation for AI agent consumption.

You are creating a directory-level roll-up summary that synthesizes the shadow docs
of all files in the directory.
You MUST use the submit_directory_shadow_doc tool to submit your documentation.
Do not include any header or metadata - just the documentation body."""

    # Build the child summaries section
    summaries_text = "\n\n---\n\n".join(
        f"**{path.name}:**\n{summary}" for path, summary in child_summaries
    )

    user_prompt = f"""Generate a directory-level shadow documentation roll-up for:

**Directory:** {relative_path}

The following are the shadow docs for files/subdirectories in this directory:

{summaries_text}

Synthesize these into a cohesive directory-level summary using the submit_directory_shadow_doc tool.
Focus on:
- The overall purpose of this directory/module
- How the components work together
- Key entry points and public API
"""

    messages = [Message(role=MessageRole.USER, content=user_prompt)]
    options = CompletionOptions(
        model=config.model,
        max_tokens=4096,
        tools=get_directory_tool_definitions(),
        tool_choice={"type": "tool", "name": "submit_directory_shadow_doc"},
    )

    result = await provider.complete(messages, system_prompt, options)

    for tool_call in result.tool_calls:
        if tool_call.name == "submit_directory_shadow_doc":
            return (tool_call.input["content"], result.input_tokens, result.output_tokens)

    raise RuntimeError(f"LLM did not call submit_directory_shadow_doc tool for {dir_path}")


async def process_file_async(
    provider: LLMProvider,
    config: Config,
    file_path: Path,
) -> ShadowResult:
    """Process a single file and generate/retrieve its shadow doc asynchronously.

    Returns ShadowResult with path, body, cached status, and any error.
    """
    shadow_path = config.shadow_path_for(file_path)

    # Check if we can use cached version
    if not is_stale(config, file_path):
        shadow_content = shadow_path.read_text(encoding="utf-8")
        body = _extract_body_from_shadow(shadow_content)
        return ShadowResult(path=file_path, body=body, cached=True)

    try:
        content = file_path.read_text(encoding="utf-8")
        numbered_content = add_line_numbers(content)
        source_hash = compute_file_hash(file_path)

        body, input_tokens, output_tokens, findings, public_symbols = await generate_file_shadow_doc_async(
            provider, config, file_path, numbered_content
        )
        full_doc = assemble_shadow_doc(
            file_path.relative_to(config.root_path), source_hash, body
        )

        # Write shadow doc
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        await _write_with_retry(shadow_path, full_doc)

        # Write findings JSON
        findings_path = config.findings_path_for(file_path)
        findings_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        findings_json = {
            "source": str(file_path.relative_to(config.root_path)),
            "source_hash": source_hash,
            "generated": timestamp,
            "findings": [
                {
                    "category": f.category,
                    "line_start": f.line_start,
                    "line_end": f.line_end,
                    "severity": f.severity,
                    "description": f.description,
                    "suggestion": f.suggestion,
                }
                for f in findings
            ],
        }
        await _write_with_retry(findings_path, json.dumps(findings_json, indent=2))

        # Write symbols JSON sidecar
        if public_symbols:
            symbols_path = config.symbols_path_for(file_path)
            symbols_path.parent.mkdir(parents=True, exist_ok=True)
            symbols_json = {
                "source": str(file_path.relative_to(config.root_path)),
                "source_hash": source_hash,
                "generated": timestamp,
                "symbols": public_symbols,
            }
            await _write_with_retry(symbols_path, json.dumps(symbols_json, indent=2))

        return ShadowResult(
            path=file_path,
            body=body,
            cached=False,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            findings=findings,
            public_symbols=public_symbols,
        )
    except Exception as e:
        return ShadowResult(path=file_path, body="", cached=False, error=str(e))


def print_progress(completed: int, total: int, path: Path, status: str) -> None:
    """Print progress update for file processing."""
    pct = completed / total * 100 if total > 0 else 0
    symbols = {
        "cached": "[cached]",
        "generated": "[OK]",
        "error": "[ERROR]",
        "processing": "[...]",
    }
    symbol = symbols.get(status, "[...]")
    print(f"\r[{completed}/{total}] {pct:.0f}% {symbol} {path.name}\033[K", end="", flush=True)
    if completed == total:
        print()


async def generate_shadows_parallel(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    files: list[Path],
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[ShadowResult]:
    """Generate shadow docs in parallel with rate limiting.

    Args:
        provider: LLM provider to use
        rate_limiter: Rate limiter for API calls
        config: Configuration
        files: List of files to process
        on_progress: Optional callback for progress updates

    Returns:
        List of ShadowResult objects
    """
    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed = 0
    total = len(files)
    lock = asyncio.Lock()

    async def process_one(file_path: Path) -> ShadowResult:
        nonlocal completed

        async with semaphore:
            # Check if cached first (no rate limiting needed)
            if not is_stale(config, file_path):
                shadow_path = config.shadow_path_for(file_path)
                shadow_content = shadow_path.read_text(encoding="utf-8")
                body = _extract_body_from_shadow(shadow_content)
                result = ShadowResult(path=file_path, body=body, cached=True)
            else:
                # Need to make API call - throttle first
                await rate_limiter.throttle()
                result = await process_file_async(provider, config, file_path)
                # Record actual token usage from API response
                if not result.cached and not result.error:
                    rate_limiter.record_usage(
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                    )

            async with lock:
                completed += 1
                if on_progress:
                    status = "cached" if result.cached else ("error" if result.error else "generated")
                    on_progress(completed, total, file_path, status)

            return result

    tasks = [process_one(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to ShadowResults
    final_results: list[ShadowResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append(
                ShadowResult(path=files[i], body="", cached=False, error=str(result))
            )
        else:
            final_results.append(result)

    return final_results


async def generate_directory_shadows(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    file_results: list[ShadowResult],
    all_files: list[Path],
    all_dirs: list[Path],
    verbose: bool = False,
) -> tuple[dict[Path, str], dict[Path, str], list[tuple[Path, str]]]:
    """Generate directory roll-up shadow docs with dependency-based parallelism.

    Directories are processed as soon as all their children (files + subdirs)
    are complete, maximizing parallelism while respecting dependencies.

    Args:
        provider: LLM provider to use
        rate_limiter: Rate limiter for API calls
        config: Configuration
        file_results: Results from file processing
        all_files: List of all discovered files
        all_dirs: List of all discovered directories
        verbose: If True, print detailed progress

    Returns:
        Tuple of (dir_bodies dict, dir_children_hashes dict, dir_errors list)
    """
    # Build file bodies dict from results
    file_bodies: dict[Path, str] = {}
    for result in file_results:
        if not result.error:
            file_bodies[result.path] = result.body

    # Shared state protected by lock
    dir_bodies: dict[Path, str] = {}
    dir_children_hashes: dict[Path, str] = {}
    dir_errors: list[tuple[Path, str]] = []
    lock = asyncio.Lock()

    # Build dependency info for each directory
    # pending_children[dir] = set of child directories not yet complete
    pending_children: dict[Path, set[Path]] = {}
    # parent_of[child_dir] = parent_dir
    parent_of: dict[Path, Path] = {}

    for dir_path in all_dirs:
        child_dirs = set(get_child_directories(dir_path, all_dirs))
        pending_children[dir_path] = child_dirs
        for child_dir in child_dirs:
            parent_of[child_dir] = dir_path

    # Queue of directories ready to process
    ready_queue: asyncio.Queue[Path] = asyncio.Queue()

    # Find initially ready directories (no pending child directories)
    for dir_path in all_dirs:
        if not pending_children[dir_path]:
            await ready_queue.put(dir_path)

    # Track completion
    completed_count = 0
    total_dirs = len(all_dirs)

    async def process_directory(dir_path: Path) -> None:
        """Process a single directory and notify parent when done."""
        nonlocal completed_count

        relative_path = dir_path.relative_to(config.root_path)
        if relative_path == Path("."):
            relative_path = Path("(root)")

        try:
            # Build child_entries for Merkle hash
            child_entries: list[tuple[str, str]] = []

            # Child files: (name, file_content_hash)
            for file_path in get_direct_children(config, dir_path, all_files):
                if file_path in file_bodies:
                    child_entries.append((file_path.name, compute_file_hash(file_path)))

            # Child dirs: (name, children_hash) — already computed (bottom-up)
            async with lock:
                for child_dir in get_child_directories(dir_path, all_dirs):
                    if child_dir in dir_children_hashes:
                        child_entries.append((child_dir.name, dir_children_hashes[child_dir]))

            current_hash = compute_children_hash(child_entries)

            # Check if cached
            if not is_directory_stale(config, dir_path, current_hash):
                print(f"  [cached] {relative_path}/", flush=True)
                shadow_path = config.shadow_path_for_dir(dir_path)
                shadow_content = shadow_path.read_text(encoding="utf-8")
                body = _extract_body_from_shadow(shadow_content)
                async with lock:
                    dir_bodies[dir_path] = body
                    dir_children_hashes[dir_path] = current_hash
                    completed_count += 1
                    if dir_path in parent_of:
                        parent = parent_of[dir_path]
                        pending_children[parent].discard(dir_path)
                        if not pending_children[parent]:
                            await ready_queue.put(parent)
                return

            print(f"  [rolling up] {relative_path}/", flush=True)

            # Gather summaries for LLM call
            child_summaries: list[tuple[Path, str]] = []

            for file_path in get_direct_children(config, dir_path, all_files):
                if file_path in file_bodies:
                    child_summaries.append((file_path, file_bodies[file_path]))

            async with lock:
                for child_dir in get_child_directories(dir_path, all_dirs):
                    if child_dir in dir_bodies:
                        child_summaries.append((child_dir, dir_bodies[child_dir]))

            if not child_summaries:
                # Empty directory - mark complete and notify parent
                async with lock:
                    dir_bodies[dir_path] = ""
                    dir_children_hashes[dir_path] = current_hash
                    completed_count += 1
                    if dir_path in parent_of:
                        parent = parent_of[dir_path]
                        pending_children[parent].discard(dir_path)
                        if not pending_children[parent]:
                            await ready_queue.put(parent)
                return

            await rate_limiter.throttle()
            body, input_tokens, output_tokens = await generate_directory_shadow_doc_async(
                provider, config, dir_path, child_summaries
            )
            full_doc = assemble_directory_shadow_doc(relative_path, current_hash, body)

            # Write shadow doc
            shadow_path = config.shadow_path_for_dir(dir_path)
            shadow_path.parent.mkdir(parents=True, exist_ok=True)
            await _write_with_retry(shadow_path, full_doc)

            # Record actual token usage from API response
            rate_limiter.record_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            # Update state and notify parent
            async with lock:
                dir_bodies[dir_path] = body
                dir_children_hashes[dir_path] = current_hash
                completed_count += 1
                if dir_path in parent_of:
                    parent = parent_of[dir_path]
                    pending_children[parent].discard(dir_path)
                    if not pending_children[parent]:
                        await ready_queue.put(parent)

        except Exception as e:
            print(f"  [ERROR] {relative_path}/: {e}", flush=True)
            # Store sentinel hash so parent can still compute its hash
            sentinel_hash = compute_children_hash([])
            async with lock:
                dir_errors.append((dir_path, str(e)))
                dir_bodies[dir_path] = ""
                dir_children_hashes[dir_path] = sentinel_hash
                completed_count += 1
                if dir_path in parent_of:
                    parent = parent_of[dir_path]
                    pending_children[parent].discard(dir_path)
                    if not pending_children[parent]:
                        await ready_queue.put(parent)

    # Process directories as they become ready
    active_tasks: set[asyncio.Task] = set()

    while completed_count < total_dirs:
        # Start new tasks for ready directories
        while not ready_queue.empty():
            dir_path = await ready_queue.get()
            task = asyncio.create_task(process_directory(dir_path))
            active_tasks.add(task)
            task.add_done_callback(active_tasks.discard)

        # Wait for at least one task to complete if we have active tasks
        if active_tasks:
            done, _ = await asyncio.wait(
                active_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            # Collect exceptions (don't crash)
            for task in done:
                exc = task.exception()
                if exc:
                    dir_errors.append((Path("<unknown>"), str(exc)))
        else:
            # No active tasks and queue empty - wait a bit for queue
            await asyncio.sleep(0.01)

    # Wait for any remaining tasks
    if active_tasks:
        await asyncio.gather(*active_tasks)

    return dir_bodies, dir_children_hashes, dir_errors


async def generate_shadow_docs_async(
    config: Config,
    verbose: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> bool:
    """Async entry point for shadow generation.

    Args:
        config: Configuration for shadow generation
        verbose: If True, show detailed progress including token counts
        rate_limiter: Optional shared rate limiter. If None, creates one internally.

    Returns:
        True if all files and directories were processed successfully, False if any had errors.
    """
    print(f"Generating shadow documentation for: {config.root_path}", flush=True)

    # Discover files and directories
    print("Discovering files...", flush=True)
    files = discover_files(config)
    dirs = discover_directories(config, files)

    if not files:
        print("No source files found to process.", flush=True)
        return

    print(f"Found {len(files)} source files in {len(dirs)} directories", flush=True)
    print(f"Concurrency: {config.max_concurrency}", flush=True)

    # Create provider with logging wrapper
    provider = create_provider("anthropic")
    logging_provider = LoggingProvider(provider, verbose=verbose)

    # Create rate limiter if not provided externally
    if rate_limiter is None:
        rate_limiter = RateLimiter(get_config_with_overrides("anthropic"))

    try:
        # Process files in parallel
        import time as time_module
        file_start = time_module.monotonic()
        print("\nProcessing files:", flush=True)
        progress_callback = print_progress if not verbose else None

        if verbose:
            # In verbose mode, print each file on its own line
            def verbose_progress(completed: int, total: int, path: Path, status: str) -> None:
                relative = path.relative_to(config.root_path)
                symbols = {"cached": "[cached]", "generated": "[OK]", "error": "[ERROR]"}
                print(f"  {symbols.get(status, '[...]')} {relative}", flush=True)

            progress_callback = verbose_progress

        results = await generate_shadows_parallel(
            logging_provider, rate_limiter, config, files, progress_callback
        )

        file_elapsed = time_module.monotonic() - file_start
        print(f"\n[Files completed in {file_elapsed:.1f}s]", flush=True)

        # Report any errors
        errors = [r for r in results if r.error]
        if errors:
            print(f"\n{len(errors)} file(s) had errors:", flush=True)
            for r in errors:
                relative = r.path.relative_to(config.root_path)
                print(f"  [ERROR] {relative}: {r.error}", flush=True)

        # Directory roll-ups (sequential, bottom-up)
        dir_start = time_module.monotonic()
        print("\nRolling up directories:", flush=True)
        dir_bodies, _dir_hashes, dir_errors = await generate_directory_shadows(
            logging_provider, rate_limiter, config, results, files, dirs, verbose
        )
        dir_elapsed = time_module.monotonic() - dir_start
        print(f"[Directories completed in {dir_elapsed:.1f}s]", flush=True)

        # Report any directory errors
        if dir_errors:
            print(f"\n{len(dir_errors)} directory(ies) had errors:", flush=True)
            for dir_path, err_msg in dir_errors:
                try:
                    relative = dir_path.relative_to(config.root_path)
                except ValueError:
                    relative = dir_path
                print(f"  [ERROR] {relative}/: {err_msg}", flush=True)

        # Clean up orphan shadow docs
        print("\nCleaning up orphans...", flush=True)
        orphan_count = cleanup_orphan_shadows(config, files, dirs, verbose=verbose)
        if orphan_count > 0:
            print(f"Removed {orphan_count} orphan shadow doc(s)", flush=True)

        print(f"\nShadow documentation written to: {config.shadow_root}", flush=True)
        print(logging_provider.get_token_summary(), flush=True)

        # Print findings summary
        all_findings: list[tuple[Path, Finding]] = []
        for r in results:
            for f in r.findings:
                all_findings.append((r.path, f))

        if all_findings:
            error_count = sum(1 for _, f in all_findings if f.severity == "error")
            warn_count = sum(1 for _, f in all_findings if f.severity == "warning")
            print(f"\nCode debris findings: {len(all_findings)} issue(s) ({error_count} error(s), {warn_count} warning(s))", flush=True)
            for file_path, f in all_findings:
                relative = file_path.relative_to(config.root_path)
                severity_label = "ERROR" if f.severity == "error" else "WARN "
                line_range = f"L{f.line_start}-{f.line_end}" if f.line_start != f.line_end else f"L{f.line_start}"
                print(f"  {severity_label} {relative}:{line_range}  {f.description}", flush=True)
            print("\nRun 'docstar audit' for the full report.", flush=True)

        return not errors and not dir_errors

    finally:
        await logging_provider.close()


def cleanup_orphan_shadows(config: Config, files: list[Path], dirs: list[Path], verbose: bool = False) -> int:
    """Remove shadow docs that no longer correspond to discovered source files.

    Returns the number of orphan files removed.
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        return 0

    # Build set of expected shadow paths
    expected: set[Path] = set()
    for f in files:
        expected.add(config.shadow_path_for(f))
    for d in dirs:
        expected.add(config.shadow_path_for_dir(d))

    # Also keep the root shadow doc
    expected.add(shadow_root / "_root.shadow.md")

    # Find all existing shadow docs
    existing = list(shadow_root.rglob("*.shadow.md"))

    orphans = [p for p in existing if p not in expected]
    for orphan in orphans:
        if verbose:
            relative = orphan.relative_to(config.root_path)
            print(f"  [removing orphan] {relative}", flush=True)
        orphan.unlink()

    # Also clean up orphan findings
    findings_dir = config.root_path / ".docstar" / "findings"
    if findings_dir.exists():
        expected_findings: set[Path] = set()
        for f in files:
            expected_findings.add(config.findings_path_for(f))
        for findings_file in list(findings_dir.rglob("*.findings.json")):
            if findings_file not in expected_findings:
                if verbose:
                    relative = findings_file.relative_to(config.root_path)
                    print(f"  [removing orphan] {relative}", flush=True)
                findings_file.unlink()
                orphans.append(findings_file)

    # Also clean up orphan symbols
    symbols_dir = config.root_path / ".docstar" / "symbols"
    if symbols_dir.exists():
        expected_symbols: set[Path] = set()
        for f in files:
            expected_symbols.add(config.symbols_path_for(f))
        for symbols_file in list(symbols_dir.rglob("*.symbols.json")):
            if symbols_file not in expected_symbols:
                if verbose:
                    relative = symbols_file.relative_to(config.root_path)
                    print(f"  [removing orphan] {relative}", flush=True)
                symbols_file.unlink()
                orphans.append(symbols_file)

    # Remove empty directories (bottom-up)
    for dirpath in sorted(shadow_root.rglob("*"), key=lambda p: -len(p.parts)):
        if dirpath.is_dir() and not any(dirpath.iterdir()):
            dirpath.rmdir()
    for cleanup_dir in [findings_dir, symbols_dir]:
        if cleanup_dir.exists():
            for dirpath in sorted(cleanup_dir.rglob("*"), key=lambda p: -len(p.parts)):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    dirpath.rmdir()

    return len(orphans)


def dry_run_shadow(config: Config, verbose: bool = False) -> None:
    """Show what shadow generation would process, without making LLM calls.

    Prints file count, file list, estimated tokens, and estimated cost.
    """
    files = discover_files(config)
    dirs = discover_directories(config, files)

    if not files:
        print("No source files found to process.", flush=True)
        return

    # Calculate which are stale
    stale_files = [f for f in files if is_stale(config, f)]
    cached_files = len(files) - len(stale_files)

    print(f"Dry run for: {config.root_path}\n", flush=True)
    print(f"Total source files: {len(files)}", flush=True)
    print(f"  Would generate: {len(stale_files)}", flush=True)
    print(f"  Already cached:  {cached_files}", flush=True)
    print(f"Directories: {len(dirs)}", flush=True)

    # Estimate tokens and cost for stale files
    total_bytes = 0
    for f in stale_files:
        try:
            total_bytes += f.stat().st_size
        except OSError:
            pass

    # Rough estimate: 1 token ~ 3.3 bytes of source code
    est_input_tokens = int(total_bytes / 3.3)
    # Output typically ~20% of input for shadow docs
    est_output_tokens = int(est_input_tokens * 0.2)
    # Directory rollups add ~30% more output tokens
    est_dir_output = int(est_output_tokens * 0.3)

    total_input = est_input_tokens
    total_output = est_output_tokens + est_dir_output

    # Sonnet pricing: $3/MTok input, $15/MTok output
    est_cost = (total_input / 1_000_000 * 3.0) + (total_output / 1_000_000 * 15.0)

    print(f"\nEstimated tokens (for {len(stale_files)} file(s) to generate):", flush=True)
    print(f"  Input:  ~{total_input:,}", flush=True)
    print(f"  Output: ~{total_output:,}", flush=True)
    print(f"Estimated cost: ~${est_cost:.2f}", flush=True)

    if verbose:
        print(f"\nFiles to process ({len(stale_files)}):", flush=True)
        for f in sorted(stale_files, key=lambda p: str(p.relative_to(config.root_path))):
            relative = f.relative_to(config.root_path)
            size = f.stat().st_size
            print(f"  {relative}  ({size:,} bytes)", flush=True)

        if cached_files:
            print(f"\nCached ({cached_files}):", flush=True)
            cached = [f for f in files if not is_stale(config, f)]
            for f in sorted(cached, key=lambda p: str(p.relative_to(config.root_path))):
                relative = f.relative_to(config.root_path)
                print(f"  {relative}", flush=True)


def generate_shadow_docs(
    config: Config,
    verbose: bool = False,
    rate_limiter: RateLimiter | None = None,
) -> bool:
    """Generate shadow documentation for an entire codebase (sync wrapper).

    This is the backward-compatible sync entry point.

    Args:
        config: Configuration for shadow generation
        verbose: If True, show detailed progress
        rate_limiter: Optional shared rate limiter. If None, creates one internally.

    Returns:
        True if all files and directories were processed successfully, False if any had errors.
    """
    return asyncio.run(generate_shadow_docs_async(config, verbose=verbose, rate_limiter=rate_limiter))


# Keep sync versions for backward compatibility and non-async code paths
def process_file(
    provider: LLMProvider,
    config: Config,
    file_path: Path,
) -> tuple[Path, str]:
    """Process a single file synchronously (for backward compatibility).

    Note: This runs the async version in a new event loop.
    For new code, prefer process_file_async.
    """
    result = asyncio.run(process_file_async(provider, config, file_path))
    if result.error:
        raise RuntimeError(result.error)
    return (result.path, result.body)


def check_shadow_docs(config: Config) -> list[tuple[Path, str]]:
    """Check for stale or missing shadow docs.

    Returns a list of (path, status) tuples where status is 'missing' or 'stale'.
    """
    files = discover_files(config)
    issues: list[tuple[Path, str]] = []

    for file_path in files:
        shadow_path = config.shadow_path_for(file_path)
        relative = file_path.relative_to(config.root_path)

        if not shadow_path.exists():
            issues.append((relative, "missing"))
        elif is_stale(config, file_path):
            issues.append((relative, "stale"))

    return issues
