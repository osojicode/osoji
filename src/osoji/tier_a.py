"""Tier A verifier: deterministic verdicts for mechanical doc claims.

A packet is the finding's evidence: the claim, what namespace was searched,
what was found, and the nearest declared names when nothing was. No LLM.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .claims_docs import DocClaim
from .factreg import Location, PathRegistry, RegistryAnswer, ScriptRegistry


@dataclass
class EvidencePacket:
    claim: DocClaim
    verdict: str                     # "contradicted" | "supported" | "undecidable"
    namespace: str
    searched: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    index_revision: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claim"] = asdict(self.claim)
        d["locations"] = [asdict(l) for l in self.locations]
        return d


def _verdict(answer: RegistryAnswer) -> str:
    if not answer.complete:
        return "undecidable"
    return "supported" if answer.found else "contradicted"


def verify_doc_claims(
    claims: list[DocClaim],
    paths: PathRegistry,
    scripts: ScriptRegistry,
    index_revision: str = "",
) -> list[EvidencePacket]:
    packets: list[EvidencePacket] = []
    for claim in claims:
        if claim.kind == "script_exists":
            answer = scripts.exists(claim.name, claim.ecosystem)
        elif claim.kind == "path_exists":
            answer = paths.exists(claim.name)
        else:
            continue
        note = "" if answer.complete else "no manifest of this ecosystem in the tree; absence cannot be established"
        packets.append(EvidencePacket(
            claim=claim, verdict=_verdict(answer), namespace=answer.namespace,
            searched=list(answer.searched), locations=list(answer.locations),
            near=list(answer.near), index_revision=index_revision, note=note,
        ))
    return packets


def packet_message(p: EvidencePacket) -> str:
    what = "script" if p.claim.kind == "script_exists" else "path"
    if p.verdict == "contradicted":
        near = f"; nearest declared: {', '.join(p.near)}" if p.near else ""
        return (f"Doc names {what} `{p.claim.text}` but it is not declared in the checkout "
                f"(searched {', '.join(p.searched)}{near})")
    if p.verdict == "supported":
        where = ", ".join(f"{l.path}:{l.line}" if l.line else l.path for l in p.locations)
        return f"Doc names {what} `{p.claim.text}`; declared at {where}"
    return f"Doc names {what} `{p.claim.text}`; {p.note}"


def packet_remediation(p: EvidencePacket) -> str:
    if p.verdict != "contradicted":
        return ""
    if p.near:
        return f"Replace `{p.claim.text}` with the declared name (nearest: {p.near[0]}), or declare it."
    return f"Declare `{p.claim.text}` or remove the reference from the doc."
