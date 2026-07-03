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
    from .evidence_builders import BuildContext
    from .findings import Finding


# The closed set of evidence kinds. Like every closed-set taxonomy in osoji this
# is a falsifiable engineering claim; it has no ``other`` outlet because evidence
# kinds are produced by us (the Claim Builder), not classified from the wild —
# the outlet discipline instead lives in the trace-mining taxonomies that derive
# this set (scripts/mine_traces.py). ``surrounding_code`` and ``declared_intent``
# were added in V1-4 from the Phase B exploration traces
# (tests/fixtures/bootstrap/mining/mining-report.md); adding a kind is a
# claim-builder schema version bump (claim_builder.CLAIM_BUILDER_SCHEMA_VERSION).
EvidenceKind = Literal[
    "ast_fact",
    "cross_file_reference",
    "shadow_doc_claim",
    "scanner_metadata",
    "git_blame",
    "type_signature",
    "surrounding_code",
    "declared_intent",
]

EVIDENCE_KINDS: tuple[EvidenceKind, ...] = (
    "ast_fact",
    "cross_file_reference",
    "shadow_doc_claim",
    "scanner_metadata",
    "git_blame",
    "type_signature",
    "surrounding_code",
    "declared_intent",
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


# --- Builder contract -------------------------------------------------------
#
# An EvidenceBuilder turns a propose-time Finding into zero or more Evidence
# objects (e.g. by querying FactsDB.cross_file_references or loading shadow
# docs). Concrete builders live in :mod:`osoji.evidence_builders` (V1-4), which
# populates :data:`BUILDERS` at import; this module stays import-light because
# ``findings.py`` imports from it.


class EvidenceBuilder(ABC):
    """Assembles :class:`Evidence` for a Finding before Triage.

    Builders are registered in :data:`BUILDERS` keyed by the
    :data:`EvidenceKind` they produce, so the Claim Builder schema can be a
    configuration object (a list of kinds to invoke) rather than hardcoded
    logic — see ``osojicode/wiki`` ``concepts/self-sufficient-claims.md``.

    Builders gather *positional* evidence only (where the artifact lives, what
    surrounds it, who references it) and never raise: a builder that cannot
    gather returns ``[]``; sufficiency is the schema layer's concern.
    """

    #: The evidence kind this builder produces.
    kind: EvidenceKind

    @abstractmethod
    def build(self, finding: "Finding", ctx: "BuildContext") -> list[Evidence]:
        """Return evidence of ``self.kind`` for ``finding`` (may be empty)."""
        ...


#: Registry of evidence builders, keyed by kind. Populated by
#: :mod:`osoji.evidence_builders` at import time.
BUILDERS: dict[EvidenceKind, EvidenceBuilder] = {}
