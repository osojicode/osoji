"""Evidence schema for the unified Finding/Triage architecture (v1).

This module owns the ``Evidence`` dataclass and the closed set of evidence
``kind`` values. An ``Evidence`` is a single typed piece of support gathered
*before* Triage runs: a cross-file reference, a shadow-doc claim, scanner
metadata carried over from a legacy detector, and so on.

Scope note (V1-2): this is the schema plus a *builder skeleton* only. The
concrete evidence-gathering builders (FactsDB cross-file references, shadow-doc
assembly, etc.) land in V1-4; the ``EvidenceBuilder`` ABC and ``BUILDERS``
registry below are reserved for them and intentionally empty here.

This module must NOT import :mod:`osoji.findings` at runtime — ``findings.py``
imports ``Evidence`` from here, so a runtime back-import would be circular. The
builder skeleton references ``Finding`` only under ``TYPE_CHECKING``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids circular import
    from .findings import Finding


# The closed set of evidence kinds. Like every closed-set taxonomy in osoji this
# is a falsifiable engineering claim; unlike gap_type it has no ``other`` outlet
# yet because evidence kinds are produced by us (the Claim Builder), not
# classified from the wild. Revisit if V1-4 builders need a kind not listed here.
EvidenceKind = Literal[
    "ast_fact",
    "cross_file_reference",
    "shadow_doc_claim",
    "scanner_metadata",
    "git_blame",
    "type_signature",
]

EVIDENCE_KINDS: tuple[EvidenceKind, ...] = (
    "ast_fact",
    "cross_file_reference",
    "shadow_doc_claim",
    "scanner_metadata",
    "git_blame",
    "type_signature",
)


@dataclass(frozen=True)
class Evidence:
    """A single typed piece of evidence assembled for a Finding.

    Attributes:
        kind: Which evidence kind this is (one of :data:`EVIDENCE_KINDS`).
        weight_hint: The producer's prior on how load-bearing this evidence is,
            in ``[0, 1]``. A neutral ``0.0`` means "no prior". This field is a
            candidate for removal in v2 if measurement shows the LLM weights
            implicitly; kept now per the v1 spec.
        payload: Kind-specific structure. Shape is defined by the producing
            builder (V1-4); kept as a free-form dict so the schema can evolve
            without a migration.
    """

    kind: EvidenceKind
    weight_hint: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable mapping of this evidence."""

        return {
            "kind": self.kind,
            "weight_hint": self.weight_hint,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        """Reconstruct an :class:`Evidence` from a serialized mapping."""

        return cls(
            kind=data["kind"],
            weight_hint=data.get("weight_hint", 0.0),
            payload=dict(data.get("payload") or {}),
        )


# --- Builder skeleton (concrete builders land in V1-4) ---------------------
#
# An EvidenceBuilder turns a propose-time Finding into zero or more Evidence
# objects (e.g. by querying FactsDB.cross_file_references or loading shadow
# docs). V1-2 reserves the contract and an empty registry; no builders are
# implemented yet. Keep this skeleton tiny.


class EvidenceBuilder(ABC):
    """Assembles :class:`Evidence` for a Finding before Triage.

    Concrete builders are added in V1-4 (the Claim Builder bootstrap). They are
    registered in :data:`BUILDERS` keyed by the :data:`EvidenceKind` they
    produce, so the Claim Builder schema can be a configuration object (a list
    of kinds to invoke) rather than hardcoded logic — see
    ``osojicode/wiki`` ``concepts/self-sufficient-claims.md``.
    """

    #: The evidence kind this builder produces.
    kind: EvidenceKind

    @abstractmethod
    def build(self, finding: "Finding") -> list[Evidence]:
        """Return evidence of ``self.kind`` for ``finding`` (may be empty)."""
        ...


#: Registry of evidence builders, keyed by kind. Populated in V1-4.
BUILDERS: dict[EvidenceKind, EvidenceBuilder] = {}
