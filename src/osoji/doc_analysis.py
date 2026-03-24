"""Unified documentation analysis: classification + accuracy validation."""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .async_utils import gather_with_buffer
from .config import Config, DIRECTORY_SHADOW_FILENAME, SHADOW_DIR
from .facts import FactsDB
from .hasher import read_file_safe
from .llm.base import LLMProvider
from .llm.budgets import input_budget_for_config
from .llm.types import Message, MessageRole, CompletionOptions
from .tools import (
    get_match_doc_topics_tool_definitions,
    get_analyze_document_tool_definitions,
    get_verify_doc_finding_tool_definitions,
)
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
    search_terms: list[str] = field(default_factory=list)


@dataclass
class DocAnalysisResult:
    """Result of analyzing a single documentation file."""

    path: Path
    classification: str  # Diataxis category
    confidence: float
    classification_reason: str
    matched_shadows: list[str] = field(default_factory=list)
    findings: list[DocFinding] = field(default_factory=list)
    topic_signature: dict | None = None

    @property
    def is_debris(self) -> bool:
        return self.classification == "process_artifact"


# --- Document discovery ---


def find_doc_candidates(config: Config) -> list[Path]:
    """Find documentation file candidates in the repo.

    Excludes:
    - Files in .osoji/ (shadow docs managed separately)
    - Files matching .osojiignore patterns
    - Files matching default ignore patterns

    Uses git ls-files when available to respect .gitignore.
    """
    ignore_patterns = config.load_osojiignore()
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
        if str(relative).startswith(SHADOW_DIR):
            continue

        # Skip default ignore patterns
        if _matches_ignore(relative, config.ignore_patterns):
            continue

        # Skip .osojiignore patterns
        if _matches_ignore(relative, ignore_patterns):
            continue

        # Check if it's a doc candidate
        if config.is_doc_candidate(path):
            candidates.append(path)

    return sorted(candidates)


# --- Tier 1: Explicit reference matching (no LLM) ---


def _find_referenced_sources(
    config: Config, doc_content: str, *, doc_path: Path | None = None, facts_db: FactsDB | None = None,
) -> list[Path]:
    """Extract source file references from a documentation file.

    When *facts_db* has doc-reference entries (populated by ``osoji shadow .``),
    the lookup is a fast FactsDB query.  Otherwise falls back to regex matching
    against shadow doc filenames.
    """
    # Fast path: query FactsDB if doc references are available
    if facts_db is not None and doc_path is not None:
        relative = doc_path.relative_to(config.root_path) if doc_path.is_absolute() else doc_path
        rel_str = str(relative).replace("\\", "/")
        doc_facts = facts_db.get_file(rel_str)
        if doc_facts is not None and doc_facts.classification is not None:
            return [Path(imp.get("source", "")) for imp in doc_facts.imports if imp.get("source")]

    # Fallback: regex matching against shadow doc filenames
    return _find_referenced_sources_regex(config, doc_content)


def _find_referenced_sources_regex(config: Config, doc_content: str) -> list[Path]:
    """Regex-based source reference extraction (fallback when FactsDB has no doc entries)."""
    referenced: list[Path] = []
    shadow_root = config.shadow_root

    if not shadow_root.exists():
        return []

    source_files: dict[str, Path] = {}
    for shadow_path in shadow_root.rglob("*.shadow.md"):
        if shadow_path.name == DIRECTORY_SHADOW_FILENAME:
            continue
        relative_shadow = shadow_path.relative_to(shadow_root)
        source_str = str(relative_shadow).removesuffix(".shadow.md")
        source_path = Path(source_str)

        source_files[str(source_path).replace("\\", "/")] = source_path
        source_files[source_path.name] = source_path
        if source_path.suffix == ".py":
            parts = list(source_path.with_suffix("").parts)
            if parts and parts[0] == "src":
                parts = parts[1:]
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if len(parts) > 1:
                source_files[".".join(parts)] = source_path

    found: set[str] = set()
    for ref_key, source_path in source_files.items():
        if len(ref_key) < 4:
            continue
        if ref_key in doc_content:
            path_str = str(source_path)
            if path_str not in found:
                found.add(path_str)
                referenced.append(source_path)

    return referenced


# --- Tier 2: Topic matching (small model) ---

_MATCH_SYSTEM_PROMPT = """You are a documentation-to-code matcher. Given a documentation file and a list of source code directory summaries, identify which directories contain code relevant to this documentation.

Return the directory paths whose code is discussed, referenced, or semantically relevant to the doc — even if the doc doesn't explicitly name the files.

Be selective: only return directories that are genuinely relevant, not tangentially related.

ALSO: Populate topic_signature with a one-sentence purpose and 3-7 key topic noun phrases
describing what this documentation covers (e.g., "authentication setup", "webhook configuration")."""


def _load_directory_summaries(config: Config) -> dict[str, tuple[str, list[Path]]]:
    """Load all directory shadow doc summaries and their child file paths.

    Returns:
        Dict mapping directory relative path -> (summary_text, list of child source file paths)
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        return {}

    summaries: dict[str, tuple[str, list[Path]]] = {}

    for dir_shadow in shadow_root.rglob(DIRECTORY_SHADOW_FILENAME):
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
            if child.name == DIRECTORY_SHADOW_FILENAME:
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
) -> tuple[list[Path], int, int, dict | None]:
    """Use a small model to match a doc to relevant source files via directory summaries.

    Sends doc content + all directory summaries.
    Returns (matched_source_file_paths, input_tokens, output_tokens, topic_signature).
    """
    if not dir_summaries:
        return [], 0, 0, None

    # Build compact listing of directory summaries
    listing_parts: list[str] = []
    dir_to_files: dict[str, list[Path]] = {}
    for dir_path, (summary, child_files) in dir_summaries.items():
        display_path = dir_path or "(root)"
        listing_parts.append(f"### `{display_path}/`\n{summary[:300]}\n")
        dir_to_files[dir_path] = child_files

    listing = "\n".join(listing_parts)

    # Truncate doc for small model (keep it lean)
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
            model=config.model_for("small"),
            max_tokens=1024,
            max_input_tokens=input_budget_for_config(config),
            reservation_key="doc.match_topics",
            tools=get_match_doc_topics_tool_definitions(),
            tool_choice={"type": "tool", "name": "match_doc_topics"},
        ),
    )

    matched_files: list[Path] = []
    topic_signature = None
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
            topic_signature = tool_call.input.get("topic_signature")

    return matched_files, result.input_tokens, result.output_tokens, topic_signature


# --- Unified analysis (large model) ---

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

Severity rules — commission vs omission:
- If a doc file states something that contradicts the actual codebase (wrong path, wrong
  behavior, wrong API, wrong location of a file or module), classify as severity=error
  (commission — actively misleading).
- If it merely omits information (doesn't mention a module, skips a feature), classify as
  severity=warning (omission — incomplete but not wrong).

For each finding, include the shadow doc path and a brief verbatim evidence quote.

For each finding, also provide `search_terms`: the specific technical identifiers (command names,
function names, config keys, CLI flags, file paths, etc.) that the finding makes claims about.
These are used to search the broader project for corroborating or contradicting evidence.

You MUST call the analyze_document tool with all required fields.
Always include a `findings` array. If the document has no issues, return `findings: []`."""


async def _analyze_document_async(
    provider: LLMProvider,
    config: Config,
    doc_path: Path,
    doc_content: str,
    shadow_contexts: list[tuple[Path, str]],
    rules_text: str,
) -> tuple[DocAnalysisResult, int, int]:
    """Analyze a single doc: classify + validate in one LLM call.

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

    user_prompt += (
        "\nClassify this document and validate its accuracy using the analyze_document tool. "
        "The tool call MUST include `classification`, `confidence`, `classification_reason`, and `findings`. "
        "If there are no issues, return `findings: []`."
    )

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content=user_prompt)],
        system=_ANALYZE_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("large"),
            max_tokens=2048,
            max_input_tokens=input_budget_for_config(config),
            reservation_key="doc.analyze",
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
                    search_terms=f.get("search_terms", []),
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


# --- Tier 4: Error-finding verification ---

_VERIFY_SYSTEM_PROMPT = """You are a documentation accuracy verifier performing a second-pass review.

You are given error-severity findings from an initial documentation analysis, along with
additional grep evidence from project files that were NOT available during the initial analysis.

The initial analysis only had access to shadow docs (AI-generated summaries of source files).
Now you have raw grep matches from the full project — config files, build manifests, entry point
registrations, etc. — that may confirm or contradict the original findings.

For each finding, decide:
- **upheld**: The finding is correct. The additional evidence confirms or does not contradict it.
- **retracted**: The finding is a false positive. The grep evidence shows the documented claim
  is actually correct (e.g. a command IS registered as an entry point, a config key DOES exist
  in a config file, a flag IS defined somewhere the initial analysis didn't see).
- **downgraded**: The finding has some merit but the additional evidence makes it less certain.
  Downgrade from error to warning.

Provide a verdict for EVERY finding listed."""


def _gather_project_evidence(
    config: Config, finding: DocFinding,
) -> list[tuple[str, str]]:
    """Grep non-shadowed project files for search terms from a finding.

    Returns list of (relative_path, excerpt) tuples.
    Pure Python, no LLM calls.
    """
    if not finding.search_terms:
        return []

    shadow_root = config.shadow_root
    all_paths, _ = list_repo_files(config)
    all_paths = list(all_paths)

    osojiignore = config.load_osojiignore()

    # Build set of files that already have shadow docs (model already saw these)
    shadowed_files: set[str] = set()
    if shadow_root.exists():
        for shadow_path in shadow_root.rglob("*.shadow.md"):
            if shadow_path.name == DIRECTORY_SHADOW_FILENAME:
                continue
            relative_shadow = shadow_path.relative_to(shadow_root)
            source_str = str(relative_shadow).removesuffix(".shadow.md").replace("\\", "/")
            shadowed_files.add(source_str)

    evidence: list[tuple[str, str]] = []
    files_found = 0
    _MAX_FILES = 10
    _MAX_CHARS_PER_FILE = 3000

    # Build a combined regex for all search terms
    escaped = [re.escape(term) for term in finding.search_terms]
    pattern = re.compile("|".join(escaped), re.IGNORECASE)

    for path in all_paths:
        if files_found >= _MAX_FILES:
            break

        if not path.is_absolute():
            path = config.root_path / path

        if not path.is_file():
            continue

        relative = path.relative_to(config.root_path)
        rel_str = str(relative).replace("\\", "/")

        # Skip .osoji/
        if rel_str.startswith(SHADOW_DIR):
            continue

        # Skip ignore patterns
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if osojiignore and _matches_ignore(relative, osojiignore):
            continue

        # Skip files that have shadow docs (model already saw those)
        if rel_str in shadowed_files:
            continue

        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue

        # Search for matches
        lines = content.split("\n")
        matching_regions: list[str] = []
        total_chars = 0

        for line_idx, line in enumerate(lines):
            if pattern.search(line):
                # Extract ±2 lines of context
                start = max(0, line_idx - 2)
                end = min(len(lines), line_idx + 3)
                context_lines = []
                for i in range(start, end):
                    marker = ">>>" if i == line_idx else "   "
                    context_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")
                region = "\n".join(context_lines)

                if total_chars + len(region) > _MAX_CHARS_PER_FILE:
                    break
                matching_regions.append(region)
                total_chars += len(region)

        if matching_regions:
            excerpt = "\n---\n".join(matching_regions)
            evidence.append((rel_str, excerpt))
            files_found += 1

    return evidence


async def _verify_error_findings_async(
    provider: LLMProvider,
    config: Config,
    doc_path: Path,
    doc_content: str,
    error_findings: list[DocFinding],
) -> tuple[list[DocFinding], int, int]:
    """Verify error-severity findings by searching for contradicting evidence.

    One medium-tier LLM call per document with errors. Presents original findings + grep evidence.
    Returns (verified_findings, input_tokens, output_tokens).
    If no additional evidence is found for ANY finding, skips the LLM call entirely.
    """
    # Gather evidence for all error findings
    all_evidence: dict[int, list[tuple[str, str]]] = {}
    has_any_evidence = False
    for i, finding in enumerate(error_findings):
        evidence = _gather_project_evidence(config, finding)
        all_evidence[i] = evidence
        if evidence:
            has_any_evidence = True

    # Skip optimization: if no additional evidence found, return findings as-is
    if not has_any_evidence:
        return error_findings, 0, 0

    # Build user prompt
    relative_path = doc_path.relative_to(config.root_path) if doc_path.is_absolute() else doc_path

    user_parts: list[str] = []
    user_parts.append(f"## Document: `{relative_path}`\n")

    # Include truncated doc content for context
    doc_preview = doc_content[:5000]
    if len(doc_content) > 5000:
        doc_preview += "\n[... truncated ...]"
    user_parts.append(f"```\n{doc_preview}\n```\n")

    user_parts.append("## Error findings to verify\n")
    for i, finding in enumerate(error_findings):
        user_parts.append(
            f"### Finding {i}: [{finding.category}] {finding.description}\n"
            f"- Evidence from: `{finding.shadow_ref}`\n"
            f"- Evidence quote: {finding.evidence}\n"
            f"- Search terms: {finding.search_terms}\n"
        )

    user_parts.append("## Additional project evidence (from grep)\n")
    for i, finding in enumerate(error_findings):
        evidence = all_evidence[i]
        if evidence:
            user_parts.append(f"### Evidence for Finding {i} (search terms: {finding.search_terms})\n")
            for file_path, excerpt in evidence:
                user_parts.append(f"**`{file_path}`:**\n```\n{excerpt}\n```\n")
        else:
            user_parts.append(f"### Evidence for Finding {i}: No additional evidence found.\n")

    user_parts.append(
        f"Provide a verdict for EVERY finding (indices 0 through {len(error_findings) - 1}) "
        "using the verify_doc_finding tool."
    )

    # Build completeness validator
    expected_indices = set(range(len(error_findings)))

    def check_completeness(tool_name: str, tool_input: dict) -> list[str]:
        if tool_name != "verify_doc_finding":
            return []
        verdicts = tool_input.get("verdicts", [])
        got_indices = {v.get("finding_index") for v in verdicts}
        missing = expected_indices - got_indices
        return [f"Missing verdict for finding index {idx}" for idx in sorted(missing)]

    result = await provider.complete(
        messages=[Message(role=MessageRole.USER, content="\n".join(user_parts))],
        system=_VERIFY_SYSTEM_PROMPT,
        options=CompletionOptions(
            model=config.model_for("medium"),
            max_tokens=max(1024, len(error_findings) * 300),
            max_input_tokens=input_budget_for_config(config),
            reservation_key="doc.verify_errors",
            tools=get_verify_doc_finding_tool_definitions(),
            tool_choice={"type": "tool", "name": "verify_doc_finding"},
            tool_input_validators=[check_completeness],
        ),
    )

    # Process verdicts
    verified: list[DocFinding | None] = list(error_findings)  # start with originals
    for tool_call in result.tool_calls:
        if tool_call.name == "verify_doc_finding":
            for verdict in tool_call.input.get("verdicts", []):
                idx = verdict.get("finding_index")
                action = verdict.get("action", "upheld")
                if idx is None or idx < 0 or idx >= len(error_findings):
                    continue

                if action == "retracted":
                    verified[idx] = None
                elif action == "downgraded":
                    original = error_findings[idx]
                    verified[idx] = DocFinding(
                        category=original.category,
                        severity="warning",
                        description=original.description,
                        shadow_ref=original.shadow_ref,
                        evidence=original.evidence,
                        remediation=original.remediation,
                        search_terms=original.search_terms,
                    )
                # "upheld" -> keep as-is

    # Filter out retracted (None) entries
    return (
        [f for f in verified if f is not None],
        result.input_tokens,
        result.output_tokens,
    )


# --- Orchestration ---

# Cap total shadow doc content per document to ~300K chars (~75K tokens)
_SHADOW_CHAR_CAP = 300_000


async def analyze_docs_async(
    provider: LLMProvider,
    config: Config,
    on_progress: Callable[[int, int, Path, str], None] | None = None,
) -> list[DocAnalysisResult]:
    """Orchestrate: discover docs -> match shadows -> analyze in parallel."""
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    shadow_root = config.shadow_root
    if not shadow_root.exists():
        if not config.quiet:
            print("  [skip] No shadow docs found. Run 'osoji shadow .' first.", flush=True)
        return []

    rules_text = config.load_rules_text()

    # Load directory summaries once (file I/O only)
    dir_summaries = _load_directory_summaries(config)

    # Load FactsDB once for doc-to-source reference lookups
    facts_db = FactsDB(config)

    completed = 0
    total = len(candidates)
    lock = asyncio.Lock()
    results: list[DocAnalysisResult] = []

    async def process_one(doc_path: Path) -> DocAnalysisResult | None:
        nonlocal completed

        try:
            # Read doc content (safe encoding)
            try:
                content, is_binary = read_file_safe(doc_path)
                if is_binary:
                    async with lock:
                        completed += 1
                        if on_progress:
                            on_progress(completed, total, doc_path, "error")
                    return None
            except OSError:
                async with lock:
                    completed += 1
                    if on_progress:
                        on_progress(completed, total, doc_path, "error")
                return None

            # Truncate large docs
            if len(content) > 50000:
                content = content[:50000] + "\n\n[... content truncated ...]"

            # Tier 1: Explicit reference matching (FactsDB fast path, regex fallback)
            explicit_refs = _find_referenced_sources(
                config, content, doc_path=doc_path, facts_db=facts_db,
            )

            # Tier 2: Small-model topic matching (always runs)
            topic_matches, _topic_in, _topic_out, doc_topic_signature = await _match_topics_async(
                provider, config, content, dir_summaries
            )

            # Merge and deduplicate
            all_sources: dict[str, Path] = {}
            for p in explicit_refs:
                all_sources[str(p).replace("\\", "/")] = p
            for p in topic_matches:
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

            # Large-model analysis (classify + validate)
            analysis, _analyze_in, _analyze_out = await _analyze_document_async(
                provider, config, doc_path, content, shadow_contexts, rules_text
            )

            # Tier 4: Verify error-severity findings against full project
            error_findings = [f for f in analysis.findings if f.severity == "error"]
            if error_findings:
                verified, _v_in, _v_out = await _verify_error_findings_async(
                    provider, config, doc_path, content, error_findings
                )
                non_errors = [f for f in analysis.findings if f.severity != "error"]
                analysis.findings = non_errors + verified

            # Attach topic signature from small-model matching
            analysis.topic_signature = doc_topic_signature

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
            if not config.quiet:
                print(f"  [error] {doc_path}: {e}", flush=True)
            return None

    await gather_with_buffer([lambda path=path: process_one(path) for path in candidates])

    return results


