"""Debris detection for documentation files."""

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .config import Config
from .tools import get_classify_tools, get_cross_reference_tools
from .walker import list_repo_files


def _get_sync_client() -> anthropic.Anthropic:
    """Create a sync Anthropic client for debris detection."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Please set it to your Anthropic API key."
        )
    return anthropic.Anthropic(api_key=api_key)


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


def _matches_ignore(path: Path, patterns: list[str] | set[str]) -> bool:
    """Check if path matches any ignore pattern."""
    path_str = str(path)
    for pattern in patterns:
        if fnmatch.fnmatch(path_str, pattern):
            return True
        # Also check each path component
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def classify_document(
    client: anthropic.Anthropic,
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

    # The real logic is in this prompt
    system_prompt = """You are a documentation analyst classifying files according to the Diataxis framework.

## Diataxis Framework

Documentation should serve one of four purposes:

1. **Tutorials** - Learning-oriented. Walk a beginner through a series of steps to complete a project. Focus on learning, not accomplishing.

2. **How-to guides** - Task-oriented. Guide an experienced user through steps to solve a specific problem. Assume competence.

3. **Reference** - Information-oriented. Describe the machinery. Accurate and complete. Technical description.

4. **Explanation** - Understanding-oriented. Discuss and illuminate a topic. Provide context and background.

## Process Artifacts (Debris)

Some files look like documentation but are actually development ephemera:
- Implementation prompts or instructions (e.g., "Claude, implement X...")
- Scratch notes or drafts not meant to be maintained
- Meeting notes or decision logs
- One-time migration guides
- Files with "prompt", "scratch", "WIP", "draft", "temp" in the name

Process artifacts should be classified as `process_artifact`. They mislead developers who expect maintained documentation.

## Your Task

Classify the document. Apply any project-specific rules provided. Use the classify_document tool."""

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

    response = client.messages.create(
        model=config.model,
        max_tokens=1024,
        system=system_prompt,
        tools=get_classify_tools(),
        tool_choice={"type": "tool", "name": "classify_document"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "classify_document":
            return DebrisClassification(
                path=relative_path,
                is_debris=(block.input["classification"] == "process_artifact"),
                classification=block.input["classification"],
                confidence=block.input["confidence"],
                reason=block.input["reason"],
                remediation=block.input["remediation"],
            )

    raise RuntimeError(f"LLM did not call classify_document for {doc_path}")


def detect_debris(config: Config) -> list[DebrisClassification]:
    """Scan for debris in documentation files.

    Returns list of classifications for all doc candidates.
    """
    candidates = find_doc_candidates(config)
    if not candidates:
        return []

    rules_text = config.load_rules_text()
    client = _get_sync_client()

    classifications: list[DebrisClassification] = []
    for doc_path in candidates:
        try:
            classification = classify_document(client, config, doc_path, rules_text)
            classifications.append(classification)
        except Exception as e:
            # Log error but continue with other files
            print(f"  [error] {doc_path}: {e}")

    return classifications


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


def _validate_single_doc(
    client: anthropic.Anthropic,
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

    system_prompt = """You are a documentation accuracy validator.

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

    response = client.messages.create(
        model=config.model,
        max_tokens=2048,
        system=system_prompt,
        tools=get_cross_reference_tools(),
        tool_choice={"type": "tool", "name": "submit_cross_reference_validation"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    issues: list[CrossRefIssue] = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_cross_reference_validation":
            for issue_data in block.input.get("issues", []):
                issues.append(CrossRefIssue(
                    doc_path=relative_path,
                    severity=issue_data["severity"],
                    description=issue_data["description"],
                    source_context=issue_data["source_context"],
                    remediation=issue_data["remediation"],
                ))
            return issues

    return issues


def validate_cross_references(config: Config, doc_paths: list[Path] | None = None) -> list[CrossRefIssue]:
    """Validate documentation files against shadow docs.

    Args:
        config: Docstar configuration
        doc_paths: Specific doc paths to validate (None = all candidates)

    Returns:
        List of cross-reference issues found
    """
    shadow_root = config.shadow_root
    if not shadow_root.exists():
        print("  [skip] No shadow docs found. Run 'docstar shadow .' first.")
        return []

    if doc_paths is None:
        doc_paths = find_doc_candidates(config)

    if not doc_paths:
        return []

    rules_text = config.load_rules_text()
    client = _get_sync_client()

    all_issues: list[CrossRefIssue] = []

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
            continue  # No source references, nothing to validate

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
            continue  # No shadow docs available for referenced sources

        relative = doc_path.relative_to(config.root_path)
        print(f"  [validating] {relative} (refs: {len(shadow_contexts)} source file(s))")

        try:
            issues = _validate_single_doc(
                client, config, doc_path, content, shadow_contexts, rules_text
            )
            all_issues.extend(issues)
        except Exception as e:
            print(f"  [error] {relative}: {e}")

    return all_issues
