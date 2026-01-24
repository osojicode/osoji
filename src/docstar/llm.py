"""Anthropic API wrapper with tool-forced output."""

import os
from pathlib import Path

import anthropic

from .config import Config
from .tools import get_file_tools, get_directory_tools


def get_client() -> anthropic.Anthropic:
    """Create an Anthropic client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Please set it to your Anthropic API key."
        )
    return anthropic.Anthropic(api_key=api_key)


def generate_file_shadow_doc(
    client: anthropic.Anthropic,
    config: Config,
    file_path: Path,
    numbered_content: str,
) -> str:
    """Generate a shadow doc for a single file.

    Uses tool_choice to force the LLM to call submit_shadow_doc.
    Returns the content from the tool call.
    """
    relative_path = file_path.relative_to(config.root_path)

    system_prompt = """You are a documentation expert generating shadow documentation for AI agent consumption.

Shadow docs are semantically dense summaries that help AI agents quickly understand code.
You MUST use the submit_shadow_doc tool to submit your documentation.
Do not include any header or metadata - just the documentation body."""

    user_prompt = f"""Generate shadow documentation for the following file:

**File:** {relative_path}

```
{numbered_content}
```

Analyze this code and submit a shadow doc using the submit_shadow_doc tool.
Include line number references for key elements (e.g., "MyClass (L15-45)").
"""

    response = client.messages.create(
        model=config.model,
        max_tokens=4096,
        system=system_prompt,
        tools=get_file_tools(),
        tool_choice={"type": "tool", "name": "submit_shadow_doc"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract content from the tool use block
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_shadow_doc":
            return block.input["content"]

    raise RuntimeError(f"LLM did not call submit_shadow_doc tool for {file_path}")


def generate_directory_shadow_doc(
    client: anthropic.Anthropic,
    config: Config,
    dir_path: Path,
    child_summaries: list[tuple[Path, str]],
) -> str:
    """Generate a roll-up shadow doc for a directory.

    Uses tool_choice to force the LLM to call submit_directory_shadow_doc.
    Returns the content from the tool call.
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

    response = client.messages.create(
        model=config.model,
        max_tokens=4096,
        system=system_prompt,
        tools=get_directory_tools(),
        tool_choice={"type": "tool", "name": "submit_directory_shadow_doc"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Extract content from the tool use block
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_directory_shadow_doc":
            return block.input["content"]

    raise RuntimeError(f"LLM did not call submit_directory_shadow_doc tool for {dir_path}")
