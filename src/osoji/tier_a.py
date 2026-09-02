"""Tier A verifier: deterministic verdicts for mechanical doc claims.

A packet is the finding's evidence: the claim, what namespace was searched,
what was found, and the nearest declared names when nothing was. No LLM.
"""

from __future__ import annotations

import posixpath
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


def _doc_relative_authoritative(claim: DocClaim) -> bool:
    """True when the token is unambiguous about being relative to its own doc.

    A markdown link target resolves relative to the file that names it by
    convention, dot-prefix or not (``[x](sub/y.md)`` is still relative to
    the doc, the same as ``[x](./sub/y.md)``) -- markdown link resolution
    is a fixed rule, so this always holds.

    A dot-relative token (``./x``, ``../x``) written in prose or a backtick
    span has no other reading either -- *unless* it was read from a fenced
    shell command (``claim.in_fence``): there, ``./x`` resolves against the
    transcript's working directory, which an earlier line in the same block
    may have ``cd``-shifted away from the doc's own directory (real corpus
    cases: ``cd examples/go/fibonacci`` before ``./fibonacci.test``; a
    locally-built ``./pause_test`` binary; a downloaded ``./bin/act`` moved
    from wherever the install script extracted it) -- so a fenced dot-token
    is left to the plain fallback (`_path_candidates`, `_candidate_anchored`)
    like any other ambiguous token instead of being trusted outright.
    """
    if claim.from_link:
        return True
    if claim.in_fence:
        return False
    return claim.text.strip().startswith(("./", "../"))


def _path_candidates(claim: DocClaim) -> list[tuple[str, bool]]:
    """Root-relative and doc-relative candidates for a path claim, in priority order.

    Each entry is ``(candidate_path, is_doc_relative)``. When the token is
    doc-relative-authoritative (see above) the doc-relative candidate is
    tried first: rule 2a. Otherwise the root-relative form is tried first,
    with the doc-relative form as a fallback: rules 2b/2c -- most doc paths
    in this corpus are written root-relative, and a doc nested under a
    subdirectory sometimes names a sibling path as if its own directory
    were the repo root (the doc-relative residual class in
    rulings-fix-report.md).
    """
    root_relative = claim.name
    if not claim.doc_dir:
        return [(root_relative, False)]
    doc_relative = posixpath.normpath(posixpath.join(claim.doc_dir, claim.name))
    if doc_relative == root_relative:
        return [(root_relative, False)]
    if _doc_relative_authoritative(claim):
        return [(doc_relative, True), (root_relative, False)]
    return [(root_relative, False), (doc_relative, True)]


def _candidate_anchored(paths: PathRegistry, claim: DocClaim, candidate: str) -> bool:
    """Whether a doc-relative candidate's root is real -- the doc-relative anchor rule.

    A doc-relative candidate reached through an unambiguous relative
    reference (`_doc_relative_authoritative`) is anchored as soon as the
    doc's own directory is real -- there is no other reading of ``./x`` or
    a markdown link target. A doc-relative *fallback* candidate for a plain
    token stays unanchored unless the token's own first segment genuinely
    exists under doc_dir; otherwise a foreign-namespace token merely named
    in a nested doc (an upstream repo's `src/` layout, an RPC method name)
    would be promoted to `contradicted` just because the doc's own
    directory happens to be real -- which would defeat the anchor rule for
    every claim below the repo root.
    """
    if _doc_relative_authoritative(claim):
        return paths.has_entry(claim.doc_dir)
    first_seg = claim.name.split("/", 1)[0]
    return paths.has_entry(f"{claim.doc_dir}/{first_seg}")


def _verify_path_claim(claim: DocClaim, paths: PathRegistry, index_revision: str) -> EvidencePacket:
    candidates = _path_candidates(claim)
    tried: list[tuple[str, bool, RegistryAnswer]] = []
    for candidate, is_doc_relative in candidates:
        answer = paths.exists(candidate)
        tried.append((candidate, is_doc_relative, answer))
        if answer.found:
            note = f"resolved relative to {claim.doc_dir}: {candidate}" if is_doc_relative else answer.note
            return EvidencePacket(
                claim=claim, verdict="supported", namespace=answer.namespace,
                searched=list(answer.searched), locations=list(answer.locations),
                near=list(answer.near), index_revision=index_revision, note=note,
            )

    # Nothing found. `PathRegistry.exists()` already folds "not
    # outside_index and anchored" into `complete=True` on a miss -- for the
    # root-relative candidate that *is* the anchor rule. It is not for a
    # doc-relative candidate (the registry has no notion of doc_dir, and its
    # own naive check would trivially pass on the doc's own root segment),
    # so a doc-relative candidate is re-checked with the doc-relative anchor
    # rule instead of trusting `complete`.
    for candidate, is_doc_relative, answer in tried:
        if not answer.complete:
            continue
        if is_doc_relative and not _candidate_anchored(paths, claim, candidate):
            continue
        note = f"resolved relative to {claim.doc_dir}: {candidate}" if is_doc_relative else answer.note
        return EvidencePacket(
            claim=claim, verdict="contradicted", namespace=answer.namespace,
            searched=list(answer.searched), locations=list(answer.locations),
            near=list(answer.near), index_revision=index_revision, note=note,
        )

    # Undecidable: report the most informative miss, preferring a candidate
    # with a specific outside_index-style note over the generic anchor note.
    chosen = next((a for _, _, a in tried if a.note), tried[0][2])
    note = chosen.note or "no manifest of this ecosystem in the tree; absence cannot be established"
    return EvidencePacket(
        claim=claim, verdict="undecidable", namespace=chosen.namespace,
        searched=list(chosen.searched), locations=list(chosen.locations),
        near=list(chosen.near), index_revision=index_revision, note=note,
    )


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
        if claim.kind == "path_exists":
            packets.append(_verify_path_claim(claim, paths, index_revision))
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
