"""Obligation checking — detects cross-file contract violations using the facts database."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .facts import FactsDB


@dataclass
class ObligationViolation:
    """A detected cross-file contract violation."""

    obligation_type: str       # "string_contract"
    source_file: str           # file containing the producer/definition
    checking_file: str         # file checking against this string
    description: str
    evidence: dict             # {value, producer_context, checker_context}
    severity: str = "warning"  # heuristic, not definitive
    confidence: float = 0.5


# Pattern for plausible identifiers: snake_case, camelCase, single words
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Well-known JSON Schema and API protocol keywords — these are external
# vocabulary, never internal project contracts.
_PROTOCOL_KEYWORDS = frozenset({
    "type", "properties", "required", "items", "enum",
    "minimum", "maximum", "minItems", "maxItems", "pattern",
    "format", "description", "default", "additionalProperties",
    "allOf", "anyOf", "oneOf", "not",
    # Anthropic API block types
    "text", "tool_use",
})


def _is_plausible_identifier(value: str) -> bool:
    """Filter to snake_case, camelCase, single-word identifiers.

    Excludes user-facing sentences, URLs, multi-word strings with spaces.
    """
    if not value or " " in value or "/" in value or ":" in value:
        return False
    if len(value) > 80:
        return False
    return bool(_IDENTIFIER_RE.match(value))


def _is_test_file(path: str) -> bool:
    """Check if path is a test file."""
    parts = path.replace("\\", "/").split("/")
    return any(p == "tests" or p == "test" for p in parts) or parts[-1].startswith("test_")


def _collect_tool_names() -> set[str]:
    """Collect all LLM tool names defined in tools.py."""
    try:
        from . import tools as tools_mod
        names: set[str] = set()
        for attr_name in dir(tools_mod):
            if attr_name.startswith("get_") and attr_name.endswith("_tool_definitions"):
                fn = getattr(tools_mod, attr_name)
                try:
                    for td in fn():
                        if hasattr(td, "name"):
                            names.add(td.name)
                        elif isinstance(td, dict) and "name" in td:
                            names.add(td["name"])
                except Exception:
                    pass
        return names
    except ImportError:
        return set()


class StringContractChecker:
    """Detect mismatches between string producers and consumers across files.

    Uses the facts database to find strings that are checked (membership test,
    equality) but never produced or defined anywhere in the codebase.
    """

    def __init__(self, facts_db: FactsDB):
        self.facts = facts_db
        self._tool_names = _collect_tool_names()

    def check(self) -> list[ObligationViolation]:
        violations: list[ObligationViolation] = []

        # 1. Collect all "checked" identifier strings across all files
        checked_strings = self.facts.strings_by_usage("checked", kind="identifier")

        # 2. Collect all "produced" and "defined" identifier strings
        produced_strings = self.facts.strings_by_usage("produced", kind="identifier")
        defined_strings = self.facts.strings_by_usage("defined", kind="identifier")

        # Build value -> producing files and value -> defining files maps
        produced_values: dict[str, set[str]] = {}
        for file_path, values in produced_strings.items():
            for v in values:
                produced_values.setdefault(v, set()).add(file_path)

        defined_values: dict[str, set[str]] = {}
        for file_path, values in defined_strings.items():
            for v in values:
                defined_values.setdefault(v, set()).add(file_path)

        # 3. For each checked string, see if it has a producer or definer
        for checking_file, checked_values in checked_strings.items():
            # Skip test files — they're inherently consumers, not contract participants
            if _is_test_file(checking_file):
                continue

            for value in checked_values:
                if not _is_plausible_identifier(value):
                    continue

                # Skip well-known protocol/schema keywords (external contracts)
                if value in _PROTOCOL_KEYWORDS:
                    continue

                # Skip LLM tool names (produced by Anthropic API, not project code)
                if value in self._tool_names:
                    continue

                producers = produced_values.get(value, set())
                definers = defined_values.get(value, set())

                if producers:
                    # Has a matching producer — no violation
                    continue

                if definers:
                    # Matched only as "defined" — low confidence, skip
                    continue

                # No producer or definer anywhere — flag as violation
                # Find the context from the checking file's facts
                checker_context = self._get_string_context(checking_file, value, "checked")

                violations.append(ObligationViolation(
                    obligation_type="string_contract",
                    source_file="(no producer found)",
                    checking_file=checking_file,
                    description=f'String "{value}" is checked but never produced or defined in any project file',
                    evidence={
                        "value": value,
                        "producer_context": None,
                        "checker_context": checker_context,
                    },
                    severity="warning",
                    confidence=0.8,
                ))

        # Sort by confidence descending, then by file path
        violations.sort(key=lambda v: (-v.confidence, v.checking_file))
        return violations

    def _get_string_context(self, file_path: str, value: str, usage: str) -> str | None:
        """Get the context description for a specific string in a file."""
        facts = self.facts.get_file(file_path)
        if not facts:
            return None
        for sl in facts.string_literals:
            if sl.get("value") == value and sl.get("usage") == usage:
                return sl.get("context")
        return None
