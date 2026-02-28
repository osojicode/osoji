"""Obligation checking — detects cross-file contract violations and fragile implicit contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .facts import FactsDB


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ObligationViolation:
    """A detected cross-file contract violation (legacy model, kept for compat)."""

    obligation_type: str       # "string_contract"
    source_file: str           # file containing the producer/definition
    checking_file: str         # file checking against this string
    description: str
    evidence: dict             # {value, producer_context, checker_context}
    severity: str = "warning"  # heuristic, not definitive
    confidence: float = 0.5


@dataclass
class StringOccurrence:
    file: str
    line: int
    context: str
    comparison_source: str | None = None


@dataclass
class StringContractData:
    producers: dict[str, list[StringOccurrence]]   # value -> occurrences
    checked: dict[str, list[StringOccurrence]]      # value -> occurrences
    defined: dict[str, list[StringOccurrence]]      # value -> occurrences
    all_produced_values: set[str]                    # union of produced + defined values


@dataclass
class ContractFinding:
    finding_type: str          # "violation" or "implicit_contract"
    contract_type: str         # "string_contract", etc.
    value: str | None          # single value, or None for grouped findings
    producer_file: str
    consumer_file: str
    definer_file: str | None
    severity: str
    confidence: float
    description: str
    evidence: dict
    remediation: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


_COMMON_STRINGS = {
    "id", "name", "type", "error", "status", "value", "key", "data",
    "result", "message", "path", "file", "url", "true", "false", "none",
    "null", "ok", "yes", "no",
}


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class ContractChecker(ABC):
    """Base class for contract checkers.

    Each subclass detects a specific type of cross-file contract issue
    (violations, fragile implicit contracts, etc.).
    """

    def __init__(self, facts_db: FactsDB):
        self.facts = facts_db

    @property
    @abstractmethod
    def contract_type(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def find_contracts(self) -> list[ContractFinding]: ...


# ---------------------------------------------------------------------------
# String contract checker
# ---------------------------------------------------------------------------

class StringContractChecker(ContractChecker):
    """Detect mismatches between string producers and consumers across files.

    Uses a ratio-based set algorithm: if zero of N checked strings in a file
    match any global producer, the entire set is external and skipped. Partial
    matches indicate internal contracts with drift — only the unmatched strings
    are flagged.

    Also detects *fragile implicit contracts*: values that are both produced and
    checked across files with no shared definition linking them.
    """

    def __init__(self, facts_db: FactsDB):
        super().__init__(facts_db)
        self._tool_names = _collect_tool_names()
        self._data: StringContractData | None = None

    @property
    def contract_type(self) -> str:
        return "string_contract"

    @property
    def description(self) -> str:
        return "Cross-file string contract checking"

    # --- Public API ---

    def find_contracts(self) -> list[ContractFinding]:
        """Return all findings: violations + fragile implicit contracts."""
        data = self._collect_contract_data()
        findings: list[ContractFinding] = []
        findings.extend(self._check_violations(data))
        findings.extend(self._check_fragility(data))
        return findings

    def check(self) -> list[ObligationViolation]:
        """Backward-compatible wrapper — returns violations as ObligationViolation."""
        data = self._collect_contract_data()
        return self._violations_as_legacy(self._check_violations(data))

    # --- Data collection (cached) ---

    def _collect_contract_data(self) -> StringContractData:
        if self._data is not None:
            return self._data

        producers: dict[str, list[StringOccurrence]] = {}
        checked: dict[str, list[StringOccurrence]] = {}
        defined: dict[str, list[StringOccurrence]] = {}

        for file_path in self.facts.all_files():
            file_facts = self.facts.get_file(file_path)
            if not file_facts:
                continue
            for sl in file_facts.string_literals:
                if sl.get("kind") != "identifier":
                    continue
                value = sl.get("value", "")
                if not value:
                    continue
                occ = StringOccurrence(
                    file=file_path,
                    line=sl.get("line", 0),
                    context=sl.get("context", ""),
                    comparison_source=sl.get("comparison_source"),
                )
                usage = sl.get("usage", "")
                if usage == "produced":
                    producers.setdefault(value, []).append(occ)
                elif usage == "checked":
                    checked.setdefault(value, []).append(occ)
                elif usage == "defined":
                    defined.setdefault(value, []).append(occ)

        all_produced: set[str] = set()
        for values in producers.values():
            all_produced.add(values[0].file)  # just need the values as keys
        # Actually, all_produced_values is the union of produced + defined VALUE keys
        all_produced_values = set(producers.keys()) | set(defined.keys())

        self._data = StringContractData(
            producers=producers,
            checked=checked,
            defined=defined,
            all_produced_values=all_produced_values,
        )
        return self._data

    # --- Violation detection (ratio algorithm — identical to original) ---

    def _check_violations(self, data: StringContractData) -> list[ContractFinding]:
        """Ratio-based violation detection. Reimplements check() using StringContractData."""
        findings: list[ContractFinding] = []

        # Build per-file checked entries (need the full entry dicts for comparison_source)
        per_file_checked = self.facts.string_entries_by_usage("checked", kind="identifier")

        for file_path, checked_entries in per_file_checked.items():
            if _is_test_file(file_path):
                continue

            checked_values = {e["value"] for e in checked_entries}
            checked_values -= self._tool_names

            matched = checked_values & data.all_produced_values
            unmatched = checked_values - matched

            if not unmatched:
                continue
            if not matched:
                continue

            match_ratio = len(matched) / len(checked_values)
            for entry in checked_entries:
                if entry["value"] not in unmatched:
                    continue
                if self._is_external_origin(file_path, entry.get("comparison_source")):
                    continue

                checker_context = entry.get("context")
                findings.append(ContractFinding(
                    finding_type="violation",
                    contract_type="string_contract",
                    value=entry["value"],
                    producer_file="(no producer found)",
                    consumer_file=file_path,
                    definer_file=None,
                    severity="warning",
                    confidence=round(match_ratio, 2),
                    description=f'String "{entry["value"]}" is checked but never produced or defined in any project file',
                    evidence={
                        "value": entry["value"],
                        "producer_context": None,
                        "checker_context": checker_context,
                    },
                    remediation=f"Check string contract with (no producer found)",
                ))

        findings.sort(key=lambda f: (-f.confidence, f.consumer_file))
        return findings

    # --- Fragility detection ---

    def _check_fragility(self, data: StringContractData) -> list[ContractFinding]:
        """Detect implicit contracts: values produced and checked across files with no shared definer."""
        raw_findings: list[ContractFinding] = []

        shared_values = set(data.producers.keys()) & set(data.checked.keys())

        for value in shared_values:
            if not self._is_plausible_identifier(value):
                continue

            producer_files = {occ.file for occ in data.producers[value]}
            checker_files = {occ.file for occ in data.checked[value]}
            definer_files = {occ.file for occ in data.defined.get(value, [])}

            for producer_file in producer_files:
                for checker_file in checker_files:
                    if producer_file == checker_file:
                        continue

                    # Check if both sides link to a definer
                    if definer_files:
                        robust = False
                        for definer_file in definer_files:
                            producer_linked = (
                                producer_file == definer_file
                                or self._files_are_linked(producer_file, definer_file)
                            )
                            checker_linked = (
                                checker_file == definer_file
                                or self._files_are_linked(checker_file, definer_file)
                            )
                            if producer_linked and checker_linked:
                                robust = True
                                break
                        if robust:
                            continue

                    # Find representative occurrences for evidence
                    producer_occ = next(o for o in data.producers[value] if o.file == producer_file)
                    checker_occ = next(o for o in data.checked[value] if o.file == checker_file)

                    raw_findings.append(ContractFinding(
                        finding_type="implicit_contract",
                        contract_type="string_contract",
                        value=value,
                        producer_file=producer_file,
                        consumer_file=checker_file,
                        definer_file=None,
                        severity="info",
                        confidence=0.5,
                        description=f'Implicit contract: "{value}" is produced in {producer_file} and checked in {checker_file} with no shared definition',
                        evidence={
                            "value": value,
                            "producer_context": producer_occ.context,
                            "checker_context": checker_occ.context,
                            "producer_line": producer_occ.line,
                            "checker_line": checker_occ.line,
                        },
                        remediation=self._suggest_remediation(producer_file, checker_file),
                    ))

        return self._group_findings(raw_findings)

    def _files_are_linked(self, file_a: str, file_b: str) -> bool:
        """Check if file_a imports from file_b (directly or one hop)."""
        imports_a = self.facts.imports_of(file_a)
        if file_b in imports_a:
            return True
        for intermediate in imports_a:
            if file_b in self.facts.imports_of(intermediate):
                return True
        return False

    def _is_plausible_identifier(self, value: str) -> bool:
        """Filter out noise — strings too short or too common to be meaningful contracts."""
        if len(value) < 3:
            return False
        if value.lower() in _COMMON_STRINGS:
            return False
        if value in self._tool_names:
            return False
        return True

    def _group_findings(self, findings: list[ContractFinding]) -> list[ContractFinding]:
        """Group findings by (producer_file, consumer_file) pair.

        Multi-value groups get a single finding with all values listed.
        Confidence scales with count.
        """
        if not findings:
            return []

        groups: dict[tuple[str, str], list[ContractFinding]] = {}
        for f in findings:
            key = (f.producer_file, f.consumer_file)
            groups.setdefault(key, []).append(f)

        grouped: list[ContractFinding] = []
        for (producer, consumer), group in groups.items():
            if len(group) == 1:
                grouped.append(group[0])
                continue

            values = sorted({f.value for f in group if f.value})
            count = len(values)
            confidence = min(0.9, 0.5 + 0.1 * count)
            values_str = ", ".join(f'"{v}"' for v in values[:5])
            if count > 5:
                values_str += f" (+{count - 5} more)"

            grouped.append(ContractFinding(
                finding_type="implicit_contract",
                contract_type="string_contract",
                value=None,
                producer_file=producer,
                consumer_file=consumer,
                definer_file=None,
                severity="info",
                confidence=round(confidence, 2),
                description=f"{count} implicit contracts between {producer} and {consumer}: {values_str}",
                evidence={
                    "values": values,
                    "count": count,
                },
                remediation=self._suggest_remediation(producer, consumer),
            ))

        grouped.sort(key=lambda f: (-f.confidence, f.consumer_file))
        return grouped

    def _suggest_remediation(self, producer_file: str, consumer_file: str) -> str:
        """Suggest remediation based on file relationship."""
        producer_parts = PurePosixPath(producer_file).parts
        consumer_parts = PurePosixPath(consumer_file).parts

        # Find common prefix (package directory)
        common = []
        for a, b in zip(producer_parts, consumer_parts):
            if a == b:
                common.append(a)
            else:
                break

        if common:
            pkg = "/".join(common)
            return f"Extract shared constants to a module in {pkg}/"
        return "Extract shared constants to a common enum or registry module"

    # --- Legacy conversion ---

    @staticmethod
    def _violations_as_legacy(findings: list[ContractFinding]) -> list[ObligationViolation]:
        """Convert ContractFindings back to ObligationViolation for backward compat."""
        violations: list[ObligationViolation] = []
        for f in findings:
            if f.finding_type != "violation":
                continue
            violations.append(ObligationViolation(
                obligation_type=f.contract_type,
                source_file=f.producer_file,
                checking_file=f.consumer_file,
                description=f.description,
                evidence=f.evidence,
                severity=f.severity,
                confidence=f.confidence,
            ))
        return violations

    # --- External origin detection (unchanged from original) ---

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


# ---------------------------------------------------------------------------
# Registry and entry point
# ---------------------------------------------------------------------------

CONTRACT_CHECKERS: list[type[ContractChecker]] = [
    StringContractChecker,
    # Future types:
    # EnvVarContractChecker — detect env var name drift across config and code
    # EventNameContractChecker — detect event name drift across publishers/subscribers
]


def run_all_contract_checks(facts_db: FactsDB) -> list[ContractFinding]:
    """Run all registered contract checkers and return combined findings."""
    findings: list[ContractFinding] = []
    for checker_cls in CONTRACT_CHECKERS:
        checker = checker_cls(facts_db)
        findings.extend(checker.find_contracts())
    return findings
