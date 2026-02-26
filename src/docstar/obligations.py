"""Obligation checking — detects cross-file contract violations using the facts database."""

from __future__ import annotations

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

    Uses a ratio-based set algorithm: if zero of N checked strings in a file
    match any global producer, the entire set is external and skipped. Partial
    matches indicate internal contracts with drift — only the unmatched strings
    are flagged.
    """

    def __init__(self, facts_db: FactsDB):
        self.facts = facts_db
        self._tool_names = _collect_tool_names()

    def check(self) -> list[ObligationViolation]:
        violations: list[ObligationViolation] = []

        # 1. Collect per-file checked entries (full dicts with comparison_source)
        per_file_checked = self.facts.string_entries_by_usage("checked", kind="identifier")

        # 2. Collect global set of all produced and defined identifier values
        produced_strings = self.facts.strings_by_usage("produced", kind="identifier")
        defined_strings = self.facts.strings_by_usage("defined", kind="identifier")

        global_producers: set[str] = set()
        for values in produced_strings.values():
            global_producers |= values
        for values in defined_strings.values():
            global_producers |= values

        # 3. Ratio-based algorithm per file
        for file_path, checked_entries in per_file_checked.items():
            if _is_test_file(file_path):
                continue

            checked_values = {e["value"] for e in checked_entries}
            checked_values -= self._tool_names  # safety net for tool names

            matched = checked_values & global_producers
            unmatched = checked_values - matched

            if not unmatched:
                continue  # all matched — no violations
            if not matched:
                continue  # zero matches — entire contract is external

            # Partial match — flag unmatched strings
            match_ratio = len(matched) / len(checked_values)
            for entry in checked_entries:
                if entry["value"] not in unmatched:
                    continue

                # Second filter: comparison_source external check
                if self._is_external_origin(file_path, entry.get("comparison_source")):
                    continue

                checker_context = entry.get("context")
                violations.append(ObligationViolation(
                    obligation_type="string_contract",
                    source_file="(no producer found)",
                    checking_file=file_path,
                    description=f'String "{entry["value"]}" is checked but never produced or defined in any project file',
                    evidence={
                        "value": entry["value"],
                        "producer_context": None,
                        "checker_context": checker_context,
                    },
                    severity="warning",
                    confidence=round(match_ratio, 2),
                ))

        # Sort by confidence descending, then by file path
        violations.sort(key=lambda v: (-v.confidence, v.checking_file))
        return violations

    def _is_external_origin(self, file_path: str, comparison_source: str | None) -> bool:
        """Check if comparison_source traces to an external import in the file."""
        if not comparison_source:
            return False
        root = comparison_source.split(".")[0].split("[")[0].split("(")[0].strip()
        if not root:
            return False
        file_facts = self.facts.get_file(file_path)
        if not file_facts:
            return False
        for imp in file_facts.imports:
            source = imp.get("source", "")
            names = imp.get("names", [])
            if root in names and self._is_external_package(file_path, source):
                return True
            if root == source.split(".")[-1] and self._is_external_package(file_path, source):
                return True
            if "*" in names and self._is_external_package(file_path, source):
                return True
        return False

    def _is_external_package(self, importing_file: str, source: str) -> bool:
        """Check if an import source is external (not a project file)."""
        if not source:
            return False
        if source.startswith("."):
            return False  # relative imports are always internal
        resolved = self.facts._resolve_import_source(importing_file, source)
        return resolved is None
