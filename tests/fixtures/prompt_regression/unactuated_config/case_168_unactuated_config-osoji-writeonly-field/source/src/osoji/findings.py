"""Unified Finding schema for the osoji v1 architecture.

Every code-quality finding is a hypothesis about a **gap** between what the code
claims and what it does — reachability, description, or contract (with an
``uncategorized`` outlet). See ``osojicode/wiki`` ``concepts/three-gap-theory.md``
and ``specs/0001-v1-foundation.md`` (*The Finding schema (A)*).

A detector emits a :class:`Finding` with the triage-output fields
(``verdict``/``confidence``/``triage_reasoning``/``suggested_fix``/``severity``)
left ``None``; the unified Triage stage (V1-3) fills them. The ``Evidence`` list
carries support assembled before Triage runs (see :mod:`osoji.evidence`).

Naming note: ``src/osoji/shadow.py`` defines a *different*, legacy class also
called ``Finding`` (the per-file debris shape). They live in separate modules;
new code imports ``from osoji.findings import Finding``. The two are reconciled
in V1-5.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .evidence import Evidence
from .hasher import compute_hash

# Three-gap theory's closed set, with the required ``uncategorized`` safety
# valve. The proportion of findings routed to ``uncategorized`` (CE-gap rate) is
# itself a tracked metric on the taxonomy's adequacy.
GapType = Literal["reachability", "description", "contract", "uncategorized"]

# Triage-output enums. All default to None on a freshly-proposed Finding.
Verdict = Literal["confirmed", "dismissed", "uncertain"]
Severity = Literal["error", "warning", "info"]


def compute_finding_id(
    detector: str,
    path: str,
    symbol: str | None,
    contract_claim: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> str:
    """Compute the stable identity hash for a finding.

    The identity is ``(detector, path, symbol, contract_claim)``. Raw line
    numbers are deliberately **excluded** when ``symbol`` is present: a symbol is
    a stable anchor, and folding line numbers into the id would mean a cosmetic
    edit (inserting one import at the top of a file) changes the id of every
    finding below it — busting the entire file's V1-9 verdict cache, whose key is
    ``(finding.id, evidence_fingerprint)``.

    When ``symbol`` is ``None`` the ``(line_start, line_end)`` pair is appended as
    a location fallback so symbol-less findings (debris) remain distinguishable.
    Doc and contract findings already carry ``None`` lines, so they are resilient.
    A tree-sitter structural position can replace the raw-line fallback in V1-6.

    The parts are encoded with :func:`json.dumps` (not a delimiter join) so a
    separator character inside ``contract_claim`` or ``symbol`` cannot cause an
    id collision.
    """

    parts: list[Any] = [detector, path, symbol, contract_claim]
    if symbol is None:
        parts.extend([line_start, line_end])
    return compute_hash(json.dumps(parts, ensure_ascii=False))


@dataclass(frozen=True)
class Finding:
    """A single gap hypothesis produced by a detector.

    Field order differs from the spec's illustrative pseudocode (which lists
    ``id`` first): because ``id`` is computed and therefore defaulted, it must
    follow the required fields. Field order is not part of the contract.
    """

    # Identity / claim (required)
    detector: str                    # uniform "<producer>:<category>"
    gap_type: GapType
    path: str
    line_start: int | None
    line_end: int | None
    symbol: str | None
    contract_source: str             # what states the claim ("docstring", ...)
    contract_claim: str              # what the code/doc/contract states
    observed_behavior: str           # what actually happens

    # Evidence + computed identity (defaulted)
    evidence: list[Evidence] = field(default_factory=list)
    id: str = ""                     # filled in __post_init__ when empty

    # Triage outputs — None at propose time; filled by the Triage stage (V1-3).
    verdict: Verdict | None = None
    confidence: float | None = None
    triage_reasoning: str | None = None
    suggested_fix: str | None = None
    severity: Severity | None = None

    # CONTRACT-gap only (V1-5c): the string-contract taxonomy class the Triage
    # stage assigned. Stays None for every non-contract detector, so this is
    # additive for all other consumers. The proportion of contract claims
    # classified ``other`` is the CE-gap rate on the taxonomy's adequacy.
    contract_class: str | None = None

    # Incremental-audit hook (V1-9): the Claim Builder fills this in V1-4. It is
    # excluded from ``id`` — id and evidence_fingerprint are orthogonal cache
    # dimensions. Stays None in V1-2.
    evidence_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(
                self,
                "id",
                compute_finding_id(
                    self.detector,
                    self.path,
                    self.symbol,
                    self.contract_claim,
                    self.line_start,
                    self.line_end,
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping (Evidence recurses via asdict)."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        """Reconstruct a :class:`Finding`, rebuilding nested ``Evidence``.

        Mirrors the manual dict->dataclass reconstruction convention used by
        ``audit.py``. A non-empty stored ``id`` is preserved verbatim (not
        recomputed) so pinned corpus fixtures survive a round-trip.
        """

        evidence = [Evidence.from_dict(e) for e in (data.get("evidence") or [])]
        return cls(
            detector=data["detector"],
            gap_type=data["gap_type"],
            path=data["path"],
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            symbol=data.get("symbol"),
            contract_source=data["contract_source"],
            contract_claim=data["contract_claim"],
            observed_behavior=data["observed_behavior"],
            evidence=evidence,
            id=data.get("id", ""),
            verdict=data.get("verdict"),
            confidence=data.get("confidence"),
            triage_reasoning=data.get("triage_reasoning"),
            suggested_fix=data.get("suggested_fix"),
            severity=data.get("severity"),
            contract_class=data.get("contract_class"),
            evidence_fingerprint=data.get("evidence_fingerprint"),
        )
