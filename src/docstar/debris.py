"""Debris detection for documentation files."""

import fnmatch
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .config import Config
from .llm import get_client
from .tools import get_classify_tools


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
    """
    ignore_patterns = config.load_docstarignore()
    candidates: list[Path] = []

    for path in config.root_path.rglob("*"):
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
    client = get_client()

    classifications: list[DebrisClassification] = []
    for doc_path in candidates:
        try:
            classification = classify_document(client, config, doc_path, rules_text)
            classifications.append(classification)
        except Exception as e:
            # Log error but continue with other files
            print(f"  [error] {doc_path}: {e}")

    return classifications
