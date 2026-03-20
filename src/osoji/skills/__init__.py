"""Bundled AI agent skill prompts for osoji audit workflows.

Skills are agent-agnostic markdown files that any AI coding assistant can
consume.  Use ``osoji skills list`` and ``osoji skills show <name>`` from
the CLI, or import the helpers directly::

    from osoji.skills import list_skills, get_skill
"""

from __future__ import annotations

import re
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent


def list_skills() -> list[dict[str, str]]:
    """Return ``[{name, description}]`` for every bundled ``.md`` skill file."""
    results: list[dict[str, str]] = []
    for md in sorted(_SKILLS_DIR.glob("*.md")):
        name = md.stem
        description = ""
        text = md.read_text(encoding="utf-8")
        # Parse simple YAML frontmatter for description
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
                    break
        results.append({"name": name, "description": description})
    return results


def get_skill(name: str) -> str | None:
    """Return the full markdown content of a skill, or *None* if not found."""
    path = _SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
