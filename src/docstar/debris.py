"""Unified documentation analysis: classification + accuracy validation."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .llm.base import LLMProvider
from .llm.factory import create_provider
from .llm.logging import LoggingProvider
from .llm.types import Message, MessageRole, CompletionOptions
from .rate_limiter import RateLimiter, get_config_with_overrides
from .tools import get_match_doc_topics_tool_definitions, get_analyze_document_tool_definitions
from .walker import list_repo_files, _matches_ignore


# --- Data models ---


@dataclass
class DocFinding:
    """A single finding from documentation analysis."""

    category: str       # stale_content, incorrect_content, obsolete_reference, misleading_claim
    severity: str       # error, warning
    description: str
    shadow_ref: str     # source path of evidencing shadow doc
    evidence: str       # quote from shadow doc
    remediation: str


@dataclass
class DocAnalysisResult:
    """Result of analyzing a single documentation file."""

    path: Path
    classification: str  # Diataxis category
    confidence: float
    classification_reason: str
    matched_shadows: list[str] = field(default_factory=list)
    findings: list[DocFinding] = field(default_factory=list)

    @property
    def is_debris(self) -> bool:
        return self.classification == "process_artifact"


# --- Document discovery (unchanged) ---


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


# --- Tier 1: Explicit reference matching (no LLM) ---


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


# --- Tier 2: Topic matching via Haiku ---

MATCH_MODEL = "claude-haiku-4-5-20251001"

_MATCH_SYSTEM_PROMPT = """You are a documentation-to-code matcher. Given a documentation file and a list of source code directory summaries, identify which directories contain code relevant to this documentation.

Return the directory paths whose code is discussed, referenced, or semantically relevant to the doc — even if the doc doesn't explicitly name the files.

Be selective: only return directories that are genuinely relevant, not tangentially related."""


def _load_directory_summaries(config: Config) -> dict[str, tuple[str, list[Path]]]:
    """Load all directory shadow doc summaries and their child file paths.

    Returns:
        Dict mapping directory relative path -> (summary_text, list of child source file paths)
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        return {}

    summaries: dict[str, tuple[str, list[Path]]] = {}

    for dir_shadow in shadow_root.rglob("_directory.shadow.md"):
        try:
            content = dir_shadow.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Determine the directory relative path
        relative_shadow_dir = dir_shadow.parent.relative_to(shadow_root)
        dir_key = str(relative_shadow_dir).replace("\\", "/")
        if dir_key == ".":
            dir_key = ""

        # Find child file shadow docs in this directory (non-recursive)
        child_files: list[Path] = []
        for child in dir_shadow.parent.iterdir():
            if child.name == "_directory.shadow.md":
                continue
            if child.is_file() and child.name.endswith(".shadow.md"):
                source_str = str(child.relative_to(shadow_root)).removesuffix(".shadow.md")
                child_files.append(Path(source_str))

        # Truncate summary for compact listing
        summary_preview = content[:500]

        summaries[dir_key] = (summary_preview, child_files)

    return summaries


async def _match_topics_async(
    provider: LLMProvider,
    config: Config,
    doc_content: str,
    dir_summaries: dict[str, tuple[str, list[Path]]],
) -> tuple[list[Path], int, int]:
    """Use Haiku to match a doc to relevant source files via directory summaries.

    Sends doc content + all directory summaries.
    Returns (matched_source_file_paths, input_tokens, output_tokens).
    """
    if not dir_summaries:
        return [], 0, 0

    # Build compact listing of directory summaries
    listing_parts: list[str] = []
    dir_to_files: dict[str, list[Path]] = {}
    for dir_path, (summary, child_files) in dir_summaries.items():
        display_path = dir_path or "(root)"
        listing_parts.append(f"### `{display_path}/`\n{summary[:300]}\n")
        dir_to_files[dir_path] = child_files

    listing = "\n".join(listing_parts)

    # Truncate doc for Haiku (keep it lean)
    doc_preview = doc_content[:10000]
    if len(doc_content) > 10000:
        doc_preview += "\n\n[... content truncated ...]"

    user_prompt = f"""**Documentation file content:**
```
{doc_preview}
```

**Source code directories:**
{listing}

Identify which directories contain code relevant to this documentation.
Return the directory paths using the match_doc_topics tool."""

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_MATCH_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=MATCH_MODEL,
            max_tokens=1024,
            tools=get_match_doc_topics_tool_definitions(),
            tool_choice={"type": "tool", "name": "match_doc_topics"},
        ),
    )

    matched_files: list[Path] = []
    for tool_call in result.tool_calls:
        if tool_call.name == "match_doc_topics":
            for dir_path in tool_call.input.get("relevant_paths", []):
                # Normalize: strip trailing slash
                normalized = dir_path.strip("/")
                if normalized in dir_to_files:
                    matched_files.extend(dir_to_files[normalized])
                # Also check empty string for root
                elif dir_path in ("", "(root)", "(root)/"):
                    if "" in dir_to_files:
                        matched_files.extend(dir_to_files[""])

    return matched_files, result.input_tokens, result.output_tokens


ANALYZE_MODEL = "claude-opus-4-6"

# --- Unified analysis (Opus) ---

_ANALYZE_SYSTEM_PROMPT = """You are a documentation analyst performing two tasks:

## Task 1: Classification (Diataxis Framework)

Classify the document into one of:
1. **tutorial** — Learning-oriented walkthrough for beginners
2. **how-to** — Task-oriented guide for specific goals
3. **reference** — Precise technical information (API docs, specs, ADRs, design docs)
4. **explanatory** — Understanding-oriented discussion of concepts
5. **process_artifact** — Inherently temporary file created for a one-time action (debris)

**Staleness is NOT debris.** A document whose content is outdated but whose *purpose* is ongoing is stale, not disposable.

### NOT Debris (classify under the appropriate Diataxis category)
- Living planning docs (roadmaps, backlogs, milestone trackers)
- Architectural knowledge (ADRs, design docs, impact analyses, risk assessments)
- Package/project READMEs
- Durable AI agent configuration files (e.g. AGENTS.md, CLAUDE.md, .cursorrules, CONVENTIONS.md)
- Intentionally maintained decision logs

## Task 2: Accuracy Validation

If shadow documentation (source of truth) is provided, check for contradictions:
- Wrong CLI flags or command syntax
- Incorrect function signatures or parameters
- Described behaviors the code doesn't implement
- References to renamed or deleted functions/classes/files
- Outdated configuration options or defaults
- Incorrect architectural descriptions

Do NOT flag:
- Documentation that is incomplete (omits details)
- Style or formatting issues
- Documentation about things not covered by the provided shadow docs
- Claims you cannot confirm or deny from the shadow docs (inconclusive ≠ incorrect)

Each finding has a `confirmed` boolean. Set `confirmed: true` only for genuine contradictions.
Set `confirmed: false` if on reflection the evidence is inconclusive, the doc and shadow docs
are consistent, or the shadow docs simply don't cover the claim (shadow docs are summaries,
not exhaustive — absence of detail is not a contradiction).

For each finding, include the shadow doc path and a brief verbatim evidence quote.

Use the analyze_document tool with your results."""


async def _analyze_document_async(
    provider: LLMProvider,
    config: Config,
    doc_path: Path,
    doc_content: str,
    shadow_contexts: list[tuple[Path, str]],
    rules_text: str,
) -> tuple[DocAnalysisResult, int, int]:
    """Analyze a single doc: classify + validate in one Sonnet call.

    Returns (DocAnalysisResult, input_tokens, output_tokens).
    """
    relative_path = doc_path.relative_to(config.root_path)

    user_prompt = f"""**File:** `{relative_path}`

"""

    if rules_text:
        user_prompt += f"""**Project Rules:**
{rules_text}

"""

    user_prompt += f"""**Content:**
```
{doc_content}
```
"""

    if shadow_contexts:
        shadow_text = ""
        for source_path, shadow_content in shadow_contexts:
            shadow_text += f"\n\n### Source: `{source_path}`\n{shadow_content}"
        user_prompt += f"""
**Shadow documentation (source of truth):**
{shadow_text}
"""

    user_prompt += "\nClassify this document and validate its accuracy using the analyze_document tool."

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_ANALYZE_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=ANALYZE_MODEL,
            max_tokens=2048,
            tools=get_analyze_document_tool_definitions(),
            tool_choice={"type": "tool", "name": "analyze_document"},
        ),
    )

    matched_shadow_paths = [str(p) for p, _ in shadow_contexts]

    for tool_call in result.tool_calls:
        if tool_call.name == "analyze_document":
            findings: list[DocFinding] = []
            for f in tool_call.input.get("findings", []):
                # The schema includes a `confirmed` boolean so the model can
                # retract findings it reconsiders mid-generation.
                if not f.get("confirmed", False):
                    continue
                findings.append(DocFinding(
                    category=f["category"],
                    severity=f["severity"],
                    description=f["description"],
                    shadow_ref=f.get("evidence_shadow_path", ""),
                    evidence=f.get("evidence_quote", ""),
                    remediation=f["remediation"],
                ))
            return (
                DocAnalysisResult(
                    path=relative_path,
                    classification=tool_call.input["classification"],
                    confidence=tool_call.input["confidence"],
                    classification_reason=tool_call.input["classification_reason"],
                    matched_shadows=matched_shadow_paths,
                    findings=findings,
                ),
                result.input_tokens,
                result.output_tokens,
            )

    raise RuntimeError(f"LLM did not call analyze_document for {doc_path}")


# --- Orchestration ---

# Cap total shadow doc content per document to ~300K chars (~100K tokens, half Sonnet context)
_SHADOW_CHAR_CAP = 300_000


async def analyze_docs_async(
    provider: LLMProvider,
    rate_limiter: RateLimiter,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DocAnalysisResult]:
    """Orchestrate: discover docs -> match shadows -> analyze in parallel."""
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    shadow_root = config.shadow_root
    if not shadow_root.exists():
        print("  [skip] No shadow docs found. Run 'docstar shadow .' first.", flush=True)
        return []

    rules_text = config.load_rules_text()

    # Load directory summaries once (file I/O only)
    dir_summaries = _load_directory_summaries(config)

    semaphore = asyncio.Semaphore(config.max_concurrency)
    completed = 0
    total = len(candidates)
    lock = asyncio.Lock()
    results: list[DocAnalysisResult] = []

    async def process_one(doc_path: Path) -> DocAnalysisResult | None:
        nonlocal completed

        async with semaphore:
            try:
                # Read doc content
                try:
                    content = doc_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    async with lock:
                        completed += 1
                        if on_progress:
                            on_progress(completed, total, doc_path, "error")
                    return None

                # Truncate large docs
                if len(content) > 50000:
                    content = content[:50000] + "\n\n[... content truncated ...]"

                # Tier 1: Explicit reference matching (no LLM)
                explicit_refs = _find_referenced_sources(config, content)

                # Tier 2: Haiku topic matching (always runs)
                await rate_limiter.throttle()
                haiku_matches, haiku_in, haiku_out = await _match_topics_async(
                    provider, config, content, dir_summaries
                )
                rate_limiter.record_usage(input_tokens=haiku_in, output_tokens=haiku_out)

                # Merge and deduplicate
                all_sources: dict[str, Path] = {}
                for p in explicit_refs:
                    all_sources[str(p).replace("\\", "/")] = p
                for p in haiku_matches:
                    key = str(p).replace("\\", "/")
                    if key not in all_sources:
                        all_sources[key] = p

                # Load file-level shadow docs, respecting char cap
                shadow_contexts: list[tuple[Path, str]] = []
                total_chars = 0
                for source_path in all_sources.values():
                    shadow_path = shadow_root / (str(source_path) + ".shadow.md")
                    if not shadow_path.exists():
                        continue
                    try:
                        shadow_content = shadow_path.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    if total_chars + len(shadow_content) > _SHADOW_CHAR_CAP:
                        break
                    shadow_contexts.append((source_path, shadow_content))
                    total_chars += len(shadow_content)

                # Sonnet analysis (classify + validate)
                await rate_limiter.throttle()
                analysis, analyze_in, analyze_out = await _analyze_document_async(
                    provider, config, doc_path, content, shadow_contexts, rules_text
                )
                rate_limiter.record_usage(input_tokens=analyze_in, output_tokens=analyze_out)

                async with lock:
                    completed += 1
                    results.append(analysis)
                    if analysis.is_debris:
                        status = "debris"
                    elif analysis.findings:
                        status = f"found {len(analysis.findings)}"
                    else:
                        status = "ok"
                    if on_progress:
                        on_progress(completed, total, doc_path, status)
                return analysis

            except Exception as e:
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, doc_path, "error")
                print(f"  [error] {doc_path}: {e}", flush=True)
                return None

    tasks = [process_one(path) for path in candidates]
    await asyncio.gather(*tasks)

    return results


def analyze_docs(
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
    rate_limiter: RateLimiter | None = None,
) -> list[DocAnalysisResult]:
    """Unified documentation analysis (sync wrapper).

    Creates provider and rate limiter internally (unless provided), runs async analysis.
    """
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    async def _run() -> list[DocAnalysisResult]:
        provider = create_provider("anthropic")
        logging_provider = LoggingProvider(provider)
        rl = rate_limiter if rate_limiter is not None else RateLimiter(get_config_with_overrides("anthropic"))
        try:
            return await analyze_docs_async(
                logging_provider, rl, config, on_progress
            )
        finally:
            await logging_provider.close()

    return asyncio.run(_run())
