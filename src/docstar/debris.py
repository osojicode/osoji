"""Debris detection for documentation files."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config
from .llm.base import LLMProvider
from .llm.factory import create_provider
from .llm.logging import LoggingProvider
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter, get_config_with_overrides
from .tools import get_classify_tool_definitions, get_cross_reference_tool_definitions
from .walker import list_repo_files, _matches_ignore


@dataclass
class DebrisClassification:
    """Result of classifying a documentation file."""

    path: Path
    is_debris: bool
    classification: str
    confidence: float
    reason: str
    remediation: str


def find_doc_candidates(config: Config) -> list[Path]:
    """Find documentation file candidates in the repo.

    Excludes:
    - Files in .docstar/ (shadow docs managed separately)
    - Files matching .docstarignore patterns
    - Files matching default ignore patterns

    Uses git ls-files when available to respect .gitignore.
    """
    ignore_patterns = config.load_docstarignore()
    candidates: list[Path] = []

    all_paths, _used_git = list_repo_files(config)

    for path in all_paths:
        # Ensure absolute path
        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)

        # Skip shadow doc directory
        if str(relative).startswith(".docstar"):
            continue

        # Skip default ignore patterns
        if _matches_ignore(relative, config.ignore_patterns):
            continue

        # Skip .docstarignore patterns
        if _matches_ignore(relative, ignore_patterns):
            continue

        # Check if it's a doc candidate
        if config.is_doc_candidate(path):
            candidates.append(path)

    return sorted(candidates)


# --- Classification prompts ---

_CLASSIFY_SYSTEM_PROMPT = """You are a documentation analyst classifying files according to the Diataxis framework.

## Diataxis Framework

Documentation should serve one of four purposes:

1. **Tutorials** - Learning-oriented. Walk a beginner through a series of steps to complete a project. Focus on learning, not accomplishing.

2. **How-to guides** - Task-oriented. Guide an experienced user through steps to solve a specific problem. Assume competence.

3. **Reference** - Information-oriented. Describe the machinery. Accurate and complete. Technical description.

4. **Explanation** - Understanding-oriented. Discuss and illuminate a topic. Provide context and background.

## Process Artifacts (Debris)

Some files look like documentation but are actually development ephemera:
- One-off task prompts or instructions (e.g., "Claude, implement X for a specific ticket")
- Scratch notes or drafts not meant to be maintained
- Meeting notes or decision logs
- One-time migration guides
- Files with "prompt", "scratch", "WIP", "draft", "temp" in the name

NOT debris — classify as `reference`: Durable AI agent configuration files maintained
alongside the codebase (e.g. AGENTS.md, CLAUDE.md, .cursorrules, CONVENTIONS.md).
These are standing project instructions, not throwaway task prompts.

Process artifacts should be classified as `process_artifact`. They mislead developers who expect maintained documentation.

## Your Task

Classify the document. Apply any project-specific rules provided. Use the classify_document tool."""


async def classify_document_async(
    provider: LLMProvider,
    config: Config,
    doc_path: Path,
    rules_text: str,
) -> DebrisClassification:
    """Classify a single document using LLM.

    Uses tool forcing for structured output.
    """
    relative_path = doc_path.relative_to(config.root_path)
    content = doc_path.read_text(encoding="utf-8")

    # Truncate large files
    if len(content) > 50000:
        content = content[:50000] + "\n\n[... content truncated ...]"

    user_prompt = f"""**File:** `{relative_path}`

"""

    if rules_text:
        user_prompt += f"""**Project Rules:**
{rules_text}

"""

    user_prompt += f"""**Content:**
```
{content}
```

Classify this document using the classify_document tool."""

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_CLASSIFY_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model,
            max_tokens=1024,
            tools=get_classify_tool_definitions(),
            tool_choice={"type": "tool", "name": "classify_document"},
        ),
    )

    for tool_call in result.tool_calls:
        if tool_call.name == "classify_document":
            return DebrisClassification(
                path=relative_path,
                is_debris=(tool_call.input["classification"] == "process_artifact"),
                classification=tool_call.input["classification"],
                confidence=tool_call.input["confidence"],
                reason=tool_call.input["reason"],
                remediation=tool_call.input["remediation"],
            )

    raise RuntimeError(f"LLM did not call classify_document for {doc_path}")


async def detect_debris_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DebrisClassification]:
    """Scan for debris in documentation files with parallel execution.

    Args:
        provider: LLM provider for API calls
        rate_limiter: Rate limiter for API throttling
        config: Docstar configuration
        on_progress: Optional callback (completed, total, path, status)

    Returns:
        List of classifications for all doc candidates.
    """
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    rules_text = config.load_rules_text()
    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed = 0
    total = len(candidates)
    lock = asyncio.Lock()
    classifications: list[DebrisClassification] = []

    async def process_one(doc_path: Path) -> DebrisClassification | None:
        nonlocal completed

        async with semaphore:
            await rate_limiter.throttle()
            try:
                classification = await classify_document_async(
                    provider, config, doc_path, rules_text
                )
                rate_limiter.record_usage(
                    input_tokens=0,  # LoggingProvider tracks actual tokens
                    output_tokens=0,
                )
                async with lock:
                    completed += 1
                    classifications.append(classification)
                    status = "debris" if classification.is_debris else "ok"
                    if on_progress:
                        on_progress(completed, total, doc_path, status)
                return classification
            except Exception as e:
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, doc_path, "error")
                print(f"  [error] {doc_path}: {e}", flush=True)
                return None

    tasks = [process_one(path) for path in candidates]
    await asyncio.gather(*tasks)

    return classifications


def detect_debris(
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DebrisClassification]:
    """Scan for debris in documentation files (sync wrapper).

    Creates provider and rate limiter internally, runs async detection.
    """
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    async def _run() -> list[DebrisClassification]:
        provider = create_provider("anthropic")
        logging_provider = LoggingProvider(provider)
        rate_limiter = RateLimiter(get_config_with_overrides("anthropic"))
        try:
            return await detect_debris_async(
                logging_provider, rate_limiter, config, on_progress
            )
        finally:
            await logging_provider.close()

    return asyncio.run(_run())


# --- Cross-reference validation ---


@dataclass
class CrossRefIssue:
    """A cross-reference validation issue."""

    doc_path: Path
    severity: str  # "error" or "warning"
    description: str
    source_context: str
    remediation: str


def _find_referenced_sources(config: Config, doc_content: str) -> list[Path]:
    """Extract source file references from .md text.

    Looks for:
    - Relative paths (src/docstar/config.py)
    - Filenames with source extensions (config.py)
    - Module-style references (docstar.config)
    """
    referenced: list[Path] = []
    shadow_root = config.shadow_root

    # Collect all source files that have shadow docs
    if not shadow_root.exists():
        return []

    # Build a mapping: various reference forms -> source path
    source_files: dict[str, Path] = {}
    for shadow_path in shadow_root.rglob("*.shadow.md"):
        # Skip directory roll-ups
        if shadow_path.name == "_directory.shadow.md":
            continue

        # Recover source path from shadow path
        relative_shadow = shadow_path.relative_to(shadow_root)
        # Remove .shadow.md suffix
        source_str = str(relative_shadow).removesuffix(".shadow.md")
        source_path = Path(source_str)

        # Full relative path
        source_files[str(source_path).replace("\\", "/")] = source_path
        # Filename only
        source_files[source_path.name] = source_path
        # Module-style (Python)
        if source_path.suffix == ".py":
            parts = list(source_path.with_suffix("").parts)
            if parts and parts[0] == "src":
                parts = parts[1:]
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if len(parts) > 1:
                source_files[".".join(parts)] = source_path

    # Search doc content for references
    found: set[str] = set()
    for ref_key, source_path in source_files.items():
        if len(ref_key) < 4:
            continue  # Skip very short matches to avoid false positives
        if ref_key in doc_content:
            path_str = str(source_path)
            if path_str not in found:
                found.add(path_str)
                referenced.append(source_path)

    return referenced


_XREF_SYSTEM_PROMPT = """You are a documentation accuracy validator.

You are given a documentation file (.md) and shadow documentation for the source files it references.
Shadow docs are the ground truth - they accurately describe what the code does.

Your job: find contradictions between the documentation and the source code (as described by shadow docs).

Look for:
- Wrong CLI flags or command syntax
- Incorrect function signatures or parameters
- Described behaviors the code doesn't actually implement
- References to renamed or deleted functions/classes/files
- Outdated configuration options or defaults
- Incorrect architectural descriptions

Do NOT flag:
- Documentation that is incomplete (omits details)
- Style or formatting issues
- Documentation about things not covered by the provided shadow docs

Use the submit_cross_reference_validation tool with your findings."""


@dataclass
class _XRefWorkItem:
    """Pre-computed work item for cross-reference validation."""

    doc_path: Path
    content: str
    shadow_contexts: list[tuple[Path, str]]


async def _validate_single_doc_async(
    provider: LLMProvider,
    config: Config,
    doc_path: Path,
    doc_content: str,
    shadow_contexts: list[tuple[Path, str]],
    rules_text: str,
) -> list[CrossRefIssue]:
    """Validate a single .md file against shadow docs.

    Makes one LLM call per doc file.
    """
    relative_path = doc_path.relative_to(config.root_path)

    # Build shadow context
    shadow_text = ""
    for source_path, shadow_content in shadow_contexts:
        shadow_text += f"\n\n### Source: `{source_path}`\n{shadow_content}"

    user_prompt = f"""**Documentation file:** `{relative_path}`

**Content:**
```
{doc_content}
```

**Shadow documentation (source of truth):**
{shadow_text}
"""

    if rules_text:
        user_prompt += f"""
**Project rules:**
{rules_text}
"""

    user_prompt += "\nValidate the documentation against the shadow docs using the submit_cross_reference_validation tool."

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_XREF_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model,
            max_tokens=2048,
            tools=get_cross_reference_tool_definitions(),
            tool_choice={"type": "tool", "name": "submit_cross_reference_validation"},
        ),
    )

    issues: list[CrossRefIssue] = []
    for tool_call in result.tool_calls:
        if tool_call.name == "submit_cross_reference_validation":
            for issue_data in tool_call.input.get("issues", []):
                issues.append(CrossRefIssue(
                    doc_path=relative_path,
                    severity=issue_data["severity"],
                    description=issue_data["description"],
                    source_context=issue_data["source_context"],
                    remediation=issue_data["remediation"],
                ))
            return issues

    return issues


def _prepare_xref_work_items(
    config: Config, doc_paths: list[Path]
) -> list[_XRefWorkItem]:
    """Pre-compute work items for cross-reference validation.

    Reads files and finds shadow contexts (fast file I/O).
    Returns only docs that have shadow contexts to validate against.
    """
    shadow_root = config.shadow_root
    work_items: list[_XRefWorkItem] = []

    for doc_path in doc_paths:
        try:
            content = doc_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Truncate large files
        if len(content) > 50000:
            content = content[:50000] + "\n\n[... content truncated ...]"

        # Find which source files this doc references
        referenced_sources = _find_referenced_sources(config, content)
        if not referenced_sources:
            continue

        # Load shadow docs for referenced sources
        shadow_contexts: list[tuple[Path, str]] = []
        for source_path in referenced_sources:
            shadow_path = shadow_root / (str(source_path) + ".shadow.md")
            if shadow_path.exists():
                try:
                    shadow_content = shadow_path.read_text(encoding="utf-8")
                    shadow_contexts.append((source_path, shadow_content))
                except (OSError, UnicodeDecodeError):
                    continue

        if not shadow_contexts:
            continue

        work_items.append(_XRefWorkItem(
            doc_path=doc_path,
            content=content,
            shadow_contexts=shadow_contexts,
        ))

    return work_items


async def validate_cross_references_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    doc_paths: list[Path] | None = None,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[CrossRefIssue]:
    """Validate documentation files against shadow docs with parallel execution.

    Args:
        provider: LLM provider for API calls
        rate_limiter: Rate limiter for API throttling
        config: Docstar configuration
        doc_paths: Specific doc paths to validate (None = all candidates)
        on_progress: Optional callback (completed, total, path, status)

    Returns:
        List of cross-reference issues found
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        print("  [skip] No shadow docs found. Run 'docstar shadow .' first.", flush=True)
        return []

    if doc_paths is None:
        doc_paths = find_doc_candidates(config)

    if not doc_paths:
        return []

    rules_text = config.load_rules_text()

    # Pre-compute work items (file I/O, no LLM calls)
    work_items = _prepare_xref_work_items(config, doc_paths)
    if not work_items:
        return []

    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed = 0
    total = len(work_items)
    lock = asyncio.Lock()
    all_issues: list[CrossRefIssue] = []

    async def process_one(item: _XRefWorkItem) -> list[CrossRefIssue]:
        nonlocal completed

        async with semaphore:
            await rate_limiter.throttle()
            try:
                issues = await _validate_single_doc_async(
                    provider, config, item.doc_path, item.content,
                    item.shadow_contexts, rules_text
                )
                async with lock:
                    completed += 1
                    all_issues.extend(issues)
                    status = f"found {len(issues)}" if issues else "ok"
                    if on_progress:
                        on_progress(completed, total, item.doc_path, status)
                return issues
            except Exception as e:
                relative = item.doc_path.relative_to(config.root_path)
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, item.doc_path, "error")
                print(f"  [error] {relative}: {e}", flush=True)
                return []

    tasks = [process_one(item) for item in work_items]
    await asyncio.gather(*tasks)

    return all_issues


def validate_cross_references(
    config: Config,
    doc_paths: list[Path] | None = None,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[CrossRefIssue]:
    """Validate documentation files against shadow docs (sync wrapper).

    Creates provider and rate limiter internally, runs async validation.
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        print("  [skip] No shadow docs found. Run 'docstar shadow .' first.", flush=True)
        return []

    async def _run() -> list[CrossRefIssue]:
        provider = create_provider("anthropic")
        logging_provider = LoggingProvider(provider)
        rate_limiter = RateLimiter(get_config_with_overrides("anthropic"))
        try:
            return await validate_cross_references_async(
                logging_provider, rate_limiter, config, doc_paths, on_progress
            )
        finally:
            await logging_provider.close()

    return asyncio.run(_run())
