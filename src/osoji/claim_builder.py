"""The mechanized Claim Builder (V1-4, osojicode/work#27).

Assembles Findings into self-sufficient claims: per finding category a
:class:`SchemaEntry` names the evidence kinds to build (invocation order) and
the ``require_any`` sufficiency gate. The schema is **configuration, not
code** — a JSON-round-trippable table (the gepa mutation surface for v2) whose
content was ratified at the V1-4 Checkpoint 1 from the mined exploration
traces (``tests/fixtures/bootstrap/mining/mining-report.md``).

The Claim Builder also computes the deterministic ``evidence_fingerprint``
(the V1-9 verdict-cache key, reserved in V1-2): a stable hash over the
canonicalized evidence bundle, osoji's own ``impl_hash``, and
:data:`CLAIM_BUILDER_SCHEMA_VERSION` — so an upgrade to detection logic or to
this schema invalidates the whole cache (see osojicode/wiki
``concepts/incremental-audit.md``). An **empty** bundle keeps the fingerprint
``None`` (cache-ineligible): symbol-less findings can collide on ``finding.id``
and an empty-bundle fingerprint would let two distinct findings share a cached
verdict (decision 0014).

``build_debris_claims`` remains the audit Phase-3 entry point with its V1-3
contract intact; it now runs on the generalized builders with the legacy
sufficiency semantics (refs OR type definitions) encoded as ``require_any``
overrides in :data:`DEBRIS_SCHEMA`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from .config import Config
from .evidence import BUILDERS, Evidence, EvidenceKind
from .evidence_builders import (  # noqa: F401  (re-exported: legacy import sites)
    BuildContext,
    _extract_all_symbols_from_debris,
    _infer_variable_type,
    _lookup_type_definitions,
)
from .findings import Finding
from .findings_adapter import finding_from_debris
from .hasher import compute_hash, compute_impl_hash
from .triage import Claim

#: Version tag of the Claim Builder schema (kind set + tables below). Part of
#: every evidence_fingerprint; bump on any schema change so the V1-9 verdict
#: cache invalidates rather than serving verdicts produced by an older schema.
CLAIM_BUILDER_SCHEMA_VERSION = "cb-2"


@dataclass(frozen=True)
class SchemaEntry:
    """What the Claim Builder gathers for one finding category.

    Attributes:
        kinds: Evidence kinds to build, in invocation order.
        require_any: The claim is ``insufficient_evidence`` iff this set is
            non-empty and NONE of its kinds produced evidence — i.e. the
            builders could not even look, as distinct from looking and finding
            an honest zero (evidence-of-absence carries scan scope).
    """

    kinds: tuple[EvidenceKind, ...]
    require_any: frozenset[EvidenceKind] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {"kinds": list(self.kinds), "require_any": sorted(self.require_any)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaEntry":
        return cls(
            kinds=tuple(data["kinds"]),
            require_any=frozenset(data.get("require_any", ())),
        )


_REACHABILITY_ENTRY = SchemaEntry(
    kinds=("cross_file_reference", "surrounding_code"),
    require_any=frozenset({"cross_file_reference"}),
)
_CONTRACT_ENTRY = _REACHABILITY_ENTRY
_DESCRIPTION_ENTRY = SchemaEntry(
    kinds=("surrounding_code", "declared_intent", "shadow_doc_claim", "cross_file_reference"),
    require_any=frozenset({"surrounding_code"}),
)
_LATENT_BUG_ENTRY = SchemaEntry(
    kinds=("surrounding_code", "cross_file_reference", "type_signature"),
    require_any=frozenset({"cross_file_reference", "type_signature"}),
)

#: Ratified per-category schema (Checkpoint 1). Keyed by native category —
#: the part after ``:`` in ``Finding.detector``.
CLAIM_BUILDER_SCHEMA: dict[str, SchemaEntry] = {
    # reachability
    "dead_code": _REACHABILITY_ENTRY,
    "dead_symbol": _REACHABILITY_ENTRY,
    "dead_parameter": _REACHABILITY_ENTRY,
    "unactuated_config": _REACHABILITY_ENTRY,
    # contract
    "obligation_implicit_contract": _CONTRACT_ENTRY,
    "obligation_violation": _CONTRACT_ENTRY,
    # description
    "stale_comment": _DESCRIPTION_ENTRY,
    "misleading_docstring": _DESCRIPTION_ENTRY,
    "doc_incorrect_content": _DESCRIPTION_ENTRY,
    "doc_misleading_claim": _DESCRIPTION_ENTRY,
    "doc_stale_content": _DESCRIPTION_ENTRY,
    "doc_obsolete_reference": _DESCRIPTION_ENTRY,
    # uncategorized (latent bugs)
    "latent_bug": _LATENT_BUG_ENTRY,
}

#: Fallback for categories the table does not know, keyed by gap type.
DEFAULT_SCHEMA_BY_GAP_TYPE: dict[str, SchemaEntry] = {
    "reachability": _REACHABILITY_ENTRY,
    "contract": _CONTRACT_ENTRY,
    "description": _DESCRIPTION_ENTRY,
    "uncategorized": SchemaEntry(
        kinds=("surrounding_code", "cross_file_reference"),
        require_any=frozenset({"surrounding_code", "cross_file_reference"}),
    ),
}

#: Debris cutover schema: the ratified kind lists with the LEGACY sufficiency
#: gate (a claim existed iff cross-file refs OR type definitions were
#: gatherable) so the V1-3 would_escalate semantics carry over unchanged.
DEBRIS_SCHEMA: dict[str, SchemaEntry] = {
    "dead_code": _REACHABILITY_ENTRY,
    "stale_comment": replace(
        _DESCRIPTION_ENTRY, require_any=frozenset({"cross_file_reference"})
    ),
    "latent_bug": _LATENT_BUG_ENTRY,
}


def category_of(finding: Finding) -> str:
    """The native category: the part of ``detector`` after ``<producer>:``."""

    _, _, category = finding.detector.partition(":")
    return category or finding.detector


def compute_evidence_fingerprint(
    evidence: Sequence[Evidence],
    *,
    schema_version: str = CLAIM_BUILDER_SCHEMA_VERSION,
) -> str | None:
    """Deterministic hash of an evidence bundle + osoji's logic version.

    Canonicalization: each Evidence serializes with sorted keys; the bundle is
    order-insensitive (sorted serialized entries). ``None`` for an empty bundle
    — cache-ineligible by decision 0014.
    """

    if not evidence:
        return None
    canonical = sorted(
        json.dumps(ev.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        for ev in evidence
    )
    return compute_hash("\n".join([schema_version, compute_impl_hash(), *canonical]))


def build_claims(
    findings: Sequence[Finding],
    ctx: BuildContext,
    *,
    schema: Mapping[str, SchemaEntry] | None = None,
) -> list[Claim]:
    """Assemble each Finding into a self-sufficient Claim.

    Resolution order for a finding's :class:`SchemaEntry`: the ``schema``
    table by category, then :data:`DEFAULT_SCHEMA_BY_GAP_TYPE` by gap type,
    then the conservative ``uncategorized`` default.
    """

    table = schema if schema is not None else CLAIM_BUILDER_SCHEMA
    claims: list[Claim] = []
    for finding in findings:
        entry = (
            table.get(category_of(finding))
            or DEFAULT_SCHEMA_BY_GAP_TYPE.get(finding.gap_type)
            or DEFAULT_SCHEMA_BY_GAP_TYPE["uncategorized"]
        )
        built: list[Evidence] = []
        filled: set[EvidenceKind] = set()
        for kind in entry.kinds:
            builder = BUILDERS.get(kind)
            if builder is None:
                continue
            produced = builder.build(finding, ctx)
            if produced:
                filled.add(kind)
                built.extend(produced)
        insufficient = bool(entry.require_any) and not (entry.require_any & filled)
        bundle = [*finding.evidence, *built]
        claims.append(
            Claim(
                finding=replace(
                    finding,
                    evidence=bundle,
                    evidence_fingerprint=compute_evidence_fingerprint(bundle),
                ),
                insufficient_evidence=insufficient,
            )
        )
    return claims


# --- debris wrapper (V1-3 contract preserved) --------------------------------


def _is_eligible(finding: dict) -> bool:
    """Same eligibility gate as the legacy debris verify step."""

    category = finding.get("category", "")
    if category in ("dead_code", "latent_bug"):
        return True
    if category == "stale_comment" and finding.get("cross_file_verification_needed"):
        return True
    return False


def build_debris_claims(
    config: Config,
    raw_debris: list[dict],
    *,
    facts_db: Any | None = None,
    symbols_by_file: dict[str, list[dict]] | None = None,
) -> tuple[list[Claim], list[int], int]:
    """Assemble debris Claims through the mechanized builders.

    Returns ``(claims, original_indices, would_escalate)`` where
    ``original_indices[k]`` is the index into ``raw_debris`` of ``claims[k]`` —
    the unambiguous join used to map dismissed verdicts back to suppressions.
    ``would_escalate`` counts eligible findings whose ``require_any`` gate was
    unmet (the builders could not gather deciding evidence); they pass through
    unverified, never escalated here (decision 0014).
    """

    ctx = BuildContext(config, facts_db=facts_db, symbols_by_file=symbols_by_file)

    claims: list[Claim] = []
    original_indices: list[int] = []
    would_escalate = 0

    for i, finding in enumerate(raw_debris):
        if not _is_eligible(finding):
            continue
        if not (finding.get("source") or finding.get("source_path")):
            would_escalate += 1
            continue
        finding_obj = finding_from_debris(finding, root=config.root_path)
        claim = build_claims([finding_obj], ctx, schema=DEBRIS_SCHEMA)[0]
        if claim.insufficient_evidence:
            would_escalate += 1
        else:
            claims.append(claim)
            original_indices.append(i)

    return claims, original_indices, would_escalate
