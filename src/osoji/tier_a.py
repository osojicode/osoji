"""Tier A verifier: deterministic verdicts for mechanical doc claims.

A packet is the finding's evidence: the claim, what namespace was searched,
what was found, and the nearest declared names when nothing was. No LLM.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .claims_docs import DocClaim
from .config import Config
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
        if claim.kind == "path_exists" and claim.modality == "creation":
            # An instruction to create the artifact does not assert that it
            # exists, so the checkout cannot contradict it (claims_docs
            # _CREATION_RE). No namespace was searched: this is a statement
            # about the claim, not about the tree.
            packets.append(EvidencePacket(
                claim=claim, verdict="undecidable", namespace=PathRegistry.namespace,
                index_revision=index_revision,
                note="creation instruction, existence not asserted",
            ))
            continue
        if claim.kind == "script_exists":
            answer = scripts.exists(claim.name, claim.ecosystem)
            if not claim.explicit_run and not answer.found:
                # A bare `pnpm x` / `yarn x` runs a node_modules/.bin binary
                # when no script `x` is declared, and the registry indexes
                # manifests, not installed binaries -- so "not declared" is
                # not evidence that the command fails.
                packets.append(EvidencePacket(
                    claim=claim, verdict="undecidable", namespace=answer.namespace,
                    searched=list(answer.searched), index_revision=index_revision,
                    note="bare package-manager word may be a binary, not a script",
                ))
                continue
        elif claim.kind == "path_exists":
            answer = paths.exists(claim.name)
        else:
            continue
        # A registry that knows *why* it cannot answer says so itself; the
        # fallback covers the script registry's "no manifest at all" case.
        note = answer.note
        if not note and not answer.complete:
            note = "no manifest of this ecosystem in the tree; absence cannot be established"
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


def _index_revision(root: Path) -> str:
    """Return the short git sha the registries were built from ("" if unknown)."""

    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_tier_a(config: Config) -> list[EvidencePacket]:
    """Discover docs, extract literal claims, verify against the registries."""

    from .claims_docs import extract_doc_claims
    from .doc_analysis import find_doc_candidates

    paths = PathRegistry.from_config(config)
    scripts = ScriptRegistry.from_config(config)
    rev = _index_revision(config.root_path)
    packets: list[EvidencePacket] = []
    for doc in find_doc_candidates(config):
        try:
            content = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(doc.relative_to(config.root_path)).replace("\\", "/")
        claims = extract_doc_claims(rel, content)
        packets.extend(verify_doc_claims(claims, paths, scripts, index_revision=rev))
    return packets
