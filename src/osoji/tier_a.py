"""Tier A verifier: deterministic verdicts for mechanical doc claims.

A packet is the finding's evidence: the claim, what namespace was searched,
what was found, and the nearest declared names when nothing was. No LLM.
"""

from __future__ import annotations

import posixpath
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .claims_code import CodeClaim
from .claims_docs import DocClaim
from .config import Config
from .factreg import Declaration, Location, PathRegistry, RegistryAnswer, ScriptRegistry, SymbolRegistry, _near


@dataclass
class EvidencePacket:
    claim: DocClaim | CodeClaim
    verdict: str                     # "contradicted" | "supported" | "undecidable"
    namespace: str
    searched: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    near: list[str] = field(default_factory=list)
    index_revision: str = ""
    note: str = ""
    # (severity, confidence) chosen by the verifier when the grade depends on
    # the case rather than on the claim kind alone (code claims); None lets
    # the audit grade by kind.
    grade: tuple[str, float] | None = None

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


# ---------------------------------------------------------------------------
# Code claims (claims_code.py) against the path and symbol registries.
# ---------------------------------------------------------------------------

_CODE_GRADES = {
    "import_path": ("error", 1.0),
    "member_ref": ("warning", 0.8),
    "implements_member": ("error", 1.0),
    "implements_signature": ("info", 0.6),
    "call_arg_keys": ("warning", 0.7),
    "duplicate_declaration": ("warning", 0.7),
}


def _loc(decl: Declaration) -> Location:
    return Location(path=decl.file, line=decl.line)


def _packet(claim: CodeClaim, verdict: str, namespace: str, rev: str, *, note: str = "",
            searched: list[str] | None = None, locations: list[Location] | None = None,
            near: list[str] | None = None, grade: tuple[str, float] | None = None) -> EvidencePacket:
    return EvidencePacket(
        claim=claim, verdict=verdict, namespace=namespace, searched=list(searched or []),
        locations=list(locations or []), near=list(near or []), index_revision=rev, note=note,
        grade=grade if verdict == "contradicted" else None,
    )


def _verify_import(claim: CodeClaim, paths: PathRegistry, symbols: SymbolRegistry, rev: str) -> EvidencePacket:
    res = symbols.resolve_specifier(claim.doc_path, claim.text)
    if res.kind == "file" and res.file:
        return _packet(claim, "supported", paths.namespace, rev, locations=[Location(path=res.file)],
                       searched=res.candidates)
    if res.kind == "missing":
        first = res.candidates[0] if res.candidates else claim.name
        answer = paths.exists(first, anchor=False)
        grade = ("error", 0.8) if res.artefacts_ignored else _CODE_GRADES["import_path"]
        return _packet(claim, "contradicted", paths.namespace, rev, searched=res.candidates,
                       near=answer.near, grade=grade,
                       note=f"resolves to {claim.name}; no candidate exists" + (f" ({res.note})" if res.note else ""))
    notes = {"external": res.note or "bare specifier; not a path in this repository",
             "outside": res.note or "resolves outside the repository",
             "unindexed": res.note or "candidate lies outside the indexed universe"}
    return _packet(claim, "undecidable", paths.namespace, rev, searched=res.candidates,
                   note=notes.get(res.kind, res.note))


def _verify_member_ref(claim: CodeClaim, symbols: SymbolRegistry, rev: str) -> EvidencePacket:
    ns = symbols.namespace
    if claim.shadowed:
        return _packet(claim, "undecidable", ns, rev,
                       note=f"`{claim.subject}` is re-declared by an enclosing scope; the access does not bind to the module level")
    decl, why = symbols.bind(claim.doc_path, claim.subject)
    if decl is None:
        return _packet(claim, "undecidable", ns, rev, note=why)
    if decl.kind not in ("enum", "object"):
        return _packet(claim, "undecidable", ns, rev, locations=[_loc(decl)],
                       note=f"`{claim.subject}` binds to a {decl.kind}; its members are not a closed set the registry can list")
    if decl.open:
        return _packet(claim, "undecidable", ns, rev, locations=[_loc(decl)],
                       note=f"`{claim.subject}` has a spread or computed key; its members are not a closed set")
    names = decl.member_names
    searched = [f"{decl.file}:{decl.line} {decl.kind} {decl.name}"]
    if claim.name in names:
        return _packet(claim, "supported", ns, rev, locations=[_loc(decl)], searched=searched)
    near = _near(claim.name, names) or names[:5]
    grade = _CODE_GRADES["member_ref"]
    note = f"`{decl.name}` is an {decl.kind} declared at {decl.file}:{decl.line} without `{claim.name}`"
    if decl.kind == "object" and decl.annotation:
        # The annotation governs the value's shape, not the literal alone: an
        # annotation the registry cannot resolve or cannot close (external,
        # generic, index signature, foreign base) makes the claim undecidable.
        typ, why = symbols.resolve_type(decl.file, decl.annotation)
        if typ is None:
            return _packet(claim, "undecidable", ns, rev, locations=[_loc(decl)], searched=searched,
                           note=f"`{decl.name}` is annotated `{decl.annotation}`, which does not resolve in the repository ({why})")
        members, open_, unresolved = symbols.member_set(typ)
        if open_ or unresolved:
            return _packet(claim, "undecidable", ns, rev, locations=[_loc(decl)], searched=searched,
                           note=f"`{decl.name}` is annotated `{decl.annotation}`, whose members are not a closed set the registry can list")
        m = members.get(claim.name)
        if m is not None and m.get("optional"):
            if not claim.call:
                # A plain read of an absent optional member may be deliberate
                # (`expect(policy.hook).toBeUndefined()`); only a call that can
                # never fire is dead by construction.
                return _packet(claim, "undecidable", ns, rev, locations=[_loc(decl)], searched=searched,
                               note=(f"`{claim.name}` is declared optional on {decl.annotation} and absent from "
                                     f"`{decl.name}`; a read of it may be deliberate"))
            grade = ("info", 0.6)
            note = (f"`{claim.name}` is declared optional on {decl.annotation} and `{decl.name}` "
                    f"({decl.file}:{decl.line}) does not implement it: the optional call never fires")
        elif m is not None:
            note = (f"`{claim.name}` is declared required on {decl.annotation} but `{decl.name}` "
                    f"({decl.file}:{decl.line}) does not provide it")
        else:
            note = f"neither `{decl.name}` ({decl.file}:{decl.line}) nor its type {decl.annotation} declares `{claim.name}`"
    return _packet(claim, "contradicted", ns, rev, locations=[_loc(decl)], searched=searched, near=near,
                   grade=grade, note=note)


def _verify_implements(claim: CodeClaim, symbols: SymbolRegistry, rev: str) -> list[EvidencePacket]:
    from dataclasses import replace

    ns = symbols.namespace
    cls = next((d for d in symbols.declarations(claim.doc_path)
                if d.kind == "class" and d.name == claim.subject and d.line == claim.line), None)
    if cls is None:
        return [_packet(claim, "undecidable", ns, rev, note="class declaration not found in the structure facts")]
    iface, why = symbols.resolve_type(claim.doc_path, claim.target)
    if iface is None or iface.kind not in ("interface", "type"):
        return [_packet(claim, "undecidable", ns, rev,
                        note=why or f"`{claim.target}` is not an interface declared in the repository")]
    required, open_, unresolved_ifaces = symbols.member_set(iface)
    if open_:
        return [_packet(claim, "undecidable", ns, rev, locations=[_loc(iface)],
                        note=f"`{claim.target}` admits members the registry cannot list (index signature)")]
    have, _have_open, unresolved_bases = symbols.member_set(cls)
    searched = [f"{iface.file}:{iface.line} {iface.kind} {iface.name}"]
    out: list[EvidencePacket] = []
    missing = [name for name, m in required.items() if not m.get("optional") and name not in have]
    foreign = f"; base class {', '.join(unresolved_bases)} is outside the repository and may declare it" if unresolved_bases else ""
    partial = f" (interface also extends {', '.join(unresolved_ifaces)}, not followed)" if unresolved_ifaces else ""
    for name in missing:
        if unresolved_bases:
            # v0.1 (sources/0008): a base outside the repository can declare any
            # of these, and in the v0 run it usually did (10 of 11 such packets
            # were EventEmitter members). Tier A's rule: an incomplete index is
            # undecidable, never contradicted.
            out.append(_packet(replace(claim, name=name), "undecidable", ns, rev, locations=[_loc(iface)],
                               searched=searched,
                               note=f"`{claim.subject}` declares no `{name}` in the repository{foreign}{partial}"))
            continue
        out.append(_packet(replace(claim, name=name), "contradicted", ns, rev, locations=[_loc(iface)], searched=searched,
                           near=_near(name, sorted(have)), grade=_CODE_GRADES["implements_member"],
                           note=f"`{claim.subject}` declares no `{name}`, required by {claim.target}{partial}"))
    if not missing:
        out.append(_packet(claim, "supported", ns, rev, locations=[_loc(iface)], searched=searched,
                           note=(f"all required members present" + foreign + partial)))
    for name, m in required.items():
        c = have.get(name)
        if not c or m.get("kind") != "method" or c.get("kind") != "method":
            continue
        want, got = m.get("required_params"), c.get("required_params")
        if want is None or got is None or want == got:
            continue
        out.append(_packet(replace(claim, kind="implements_signature", name=name, line=int(c.get("line") or claim.line)),
                           "contradicted", ns, rev,
                           locations=[_loc(iface)], searched=searched, grade=_CODE_GRADES["implements_signature"],
                           note=(f"`{claim.subject}.{name}` declares {got} required parameter(s); "
                                 f"{claim.target}.{name} declares {want}")))
    return out


def _verify_call_arg_keys(claim: CodeClaim, symbols: SymbolRegistry, rev: str) -> list[EvidencePacket]:
    from dataclasses import replace

    ns = symbols.namespace
    if claim.spread:
        return [_packet(claim, "undecidable", ns, rev, note="argument spreads another object; its keys are not literal")]
    call = {"member": claim.target, "receiver": claim.receiver, "enclosing_class": claim.enclosing_class}
    decls, why = symbols.resolve_callee(claim.doc_path, call)
    if not decls:
        return [_packet(claim, "undecidable", ns, rev, note=why)]
    universes: list[dict[str, dict]] = []
    locations: list[Location] = []
    types: list[str] = []
    for owner, params, line in decls:
        loc = Location(path=owner.file, line=line)
        if claim.arg_index >= len(params):
            return [_packet(claim, "undecidable", ns, rev, locations=[loc],
                            note=f"`{claim.target}` at {owner.file}:{line} declares fewer parameters than the call passes")]
        param = params[claim.arg_index]
        members, why = symbols.param_member_set(owner.file, param)
        if members is None:
            return [_packet(claim, "undecidable", ns, rev, locations=[loc],
                            note=f"`{claim.target}` at {owner.file}:{line}: {why}")]
        universes.append(members)
        locations.append(loc)
        types.append(param.get("type") or "{...}")
    searched = [f"{l.path}:{l.line} {claim.target}({t})" for l, t in zip(locations, types)]
    declared = set().union(*(set(u) for u in universes))
    missing = [k for k in claim.keys if k not in declared]
    if not missing:
        return [_packet(claim, "supported", ns, rev, locations=locations, searched=searched)]
    out = []
    for key in missing:
        out.append(_packet(replace(claim, name=key, text=f"{claim.target}({{ {key} }})"), "contradicted", ns, rev,
                           locations=locations, searched=searched,
                           near=_near(key, sorted(declared)) or sorted(declared)[:5], grade=_CODE_GRADES["call_arg_keys"],
                           note=(f"`{key}` is not declared by the parameter type of any of the {len(decls)} "
                                 f"declaration(s) of `{claim.target}` ({', '.join(sorted(set(types)))}); the callee drops it")))
    return out


def _member_sig(m: dict) -> tuple:
    return (m.get("name"), m.get("kind"), bool(m.get("optional")), m.get("params"), m.get("required_params"), m.get("signature"))


def _verify_duplicate(claim: CodeClaim, symbols: SymbolRegistry, rev: str) -> EvidencePacket:
    ns = symbols.namespace
    group = [d for d in symbols.declarations_named(claim.name, {claim.subject}) if d.exported]
    me = next((d for d in group if d.file == claim.doc_path and d.line == claim.line), None)
    others = [d for d in group if d is not me and d.file != claim.doc_path]
    if me is None or not others:
        return _packet(claim, "undecidable", ns, rev, note="no other exported declaration of this name")
    mine = set(me.member_names)
    my_sigs = {_member_sig(m) for m in (me.members or [])}
    identical: list[Declaration] = []
    diverged: list[tuple[Declaration, set[str], set[str]]] = []
    for o in others:
        theirs = set(o.member_names)
        shared = mine & theirs
        containment = len(shared) / max(1, min(len(mine), len(theirs)))
        if mine == theirs and my_sigs == {_member_sig(m) for m in (o.members or [])}:
            identical.append(o)
        elif (len(shared) >= 2 and containment >= 0.5) or (mine == theirs):
            diverged.append((o, mine - theirs, theirs - mine))
    searched = [f"{o.file}:{o.line}" for o in others]
    if identical:
        note = f"identical copy of {claim.subject} {claim.name} at " + ", ".join(f"{o.file}:{o.line}" for o in identical)
        if diverged:
            note += "; diverged copy at " + ", ".join(f"{o.file}:{o.line}" for o, _, _ in diverged)
        return _packet(claim, "contradicted", ns, rev, locations=[_loc(o) for o in identical + [d for d, _, _ in diverged]],
                       searched=searched, grade=("info", 0.5), note=note)
    if diverged:
        parts = []
        for o, only_here, only_there in diverged:
            detail = []
            if only_here:
                detail.append(f"only here: {', '.join(sorted(only_here))}")
            if only_there:
                detail.append(f"only there: {', '.join(sorted(only_there))}")
            if not detail:
                detail.append("same member names, different signatures")
            parts.append(f"{o.file}:{o.line} ({'; '.join(detail)})")
        return _packet(claim, "contradicted", ns, rev, locations=[_loc(o) for o, _, _ in diverged], searched=searched,
                       grade=("warning", 0.7), note=f"diverged from the copy at " + "; ".join(parts))
    return _packet(claim, "supported", ns, rev, searched=searched,
                   note="same name, different members: not a copy")


def verify_code_claims(claims: list[CodeClaim], paths: PathRegistry, symbols: SymbolRegistry,
                       index_revision: str = "") -> list[EvidencePacket]:
    packets: list[EvidencePacket] = []
    for claim in claims:
        if claim.kind == "import_path":
            packets.append(_verify_import(claim, paths, symbols, index_revision))
        elif claim.kind == "member_ref":
            packets.append(_verify_member_ref(claim, symbols, index_revision))
        elif claim.kind == "implements_member":
            packets.extend(_verify_implements(claim, symbols, index_revision))
        elif claim.kind == "call_arg_keys":
            packets.extend(_verify_call_arg_keys(claim, symbols, index_revision))
        elif claim.kind == "duplicate_declaration":
            packets.append(_verify_duplicate(claim, symbols, index_revision))
    return packets


def _source_files(config: Config) -> list[Path]:
    """The walker's file list with the same ignore filters the registries apply."""
    from .walker import _matches_ignore, list_repo_files

    osojiignore = config.load_osojiignore()
    out: list[Path] = []
    paths, _ = list_repo_files(config)
    for path in paths:
        p = path if path.is_absolute() else config.root_path / path
        try:
            relative = p.relative_to(config.root_path)
        except ValueError:
            continue
        if _matches_ignore(relative, config.ignore_patterns):
            continue
        if osojiignore and _matches_ignore(relative, osojiignore):
            continue
        out.append(p)
    return out


def build_symbol_registry(config: Config, paths: PathRegistry) -> tuple[SymbolRegistry, dict[str, dict]]:
    """Structure facts from every plugin that has a parser for them, as one registry."""
    from .plugins import get_all_plugins

    import logging

    from .plugins.base import FactsExtractionError, PluginUnavailableError

    logger = logging.getLogger(__name__)
    files = _source_files(config)
    structure: dict[str, dict] = {}
    providers = []
    for plugin in get_all_plugins():
        mine = [f for f in files if f.suffix in plugin.extensions]
        if not mine:
            continue
        try:
            facts = plugin.extract_structure(config.root_path, mine)
        except PluginUnavailableError as exc:
            # No parser, no registry for this language: the claims it would
            # have made are simply not compiled (same degradation shadow.py
            # applies to facts extraction).
            logger.warning("[%s] structure extraction unavailable: %s (%s)", plugin.name, exc, exc.install_hint)
            continue
        except FactsExtractionError as exc:
            logger.warning("[%s] structure extraction failed: %s", plugin.name, exc)
            continue
        if facts:
            structure.update(facts)
            providers.append(plugin)

    def candidates(base: str) -> list[str]:
        out: list[str] = []
        for plugin in providers:
            for c in plugin.module_candidates(base):
                if c not in out:
                    out.append(c)
        return out or [base]

    workspace: dict[str, str] = {}
    for plugin in providers:
        workspace.update(plugin.workspace_packages(config.root_path))
    return SymbolRegistry.from_structure(structure, module_candidates=candidates,
                                        workspace_packages=workspace, paths=paths), structure


def run_tier_a_code(config: Config) -> list[EvidencePacket]:
    """Compile code claims from the tree and verify them against the registries. Zero LLM."""
    from .claims_code import extract_code_claims

    paths = PathRegistry.from_config(config)
    symbols, structure = build_symbol_registry(config, paths)
    claims = extract_code_claims(structure)
    return verify_code_claims(claims, paths, symbols, index_revision=_index_revision(config.root_path))


_CODE_WHAT = {
    "import_path": "imports", "member_ref": "reads member", "implements_member": "implements",
    "implements_signature": "implements", "call_arg_keys": "passes key", "duplicate_declaration": "declares",
}


def packet_message(p: EvidencePacket) -> str:
    if isinstance(p.claim, CodeClaim):
        return _code_packet_message(p)
    what = "script" if p.claim.kind == "script_exists" else "path"
    if p.verdict == "contradicted":
        near = f"; nearest declared: {', '.join(p.near)}" if p.near else ""
        return (f"Doc names {what} `{p.claim.text}` but it is not declared in the checkout "
                f"(searched {', '.join(p.searched)}{near})")
    if p.verdict == "supported":
        where = ", ".join(f"{l.path}:{l.line}" if l.line else l.path for l in p.locations)
        return f"Doc names {what} `{p.claim.text}`; declared at {where}"
    return f"Doc names {what} `{p.claim.text}`; {p.note}"


def _code_packet_message(p: EvidencePacket) -> str:
    c = p.claim
    if p.verdict == "contradicted":
        near = f"; nearest declared: {', '.join(p.near)}" if p.near else ""
        if c.kind == "import_path":
            return f"Code imports `{c.text}` but no module exists at {c.name} (searched {', '.join(p.searched)}{near})"
        if c.kind == "member_ref":
            return f"Code reads `{c.text}` but {p.note}{near}"
        if c.kind == "implements_member":
            return f"`{c.text}` but {p.note}{near}"
        if c.kind == "implements_signature":
            return f"`{c.text}` but {p.note}"
        if c.kind == "call_arg_keys":
            return f"Code calls `{c.text}` but `{c.name}` {p.note.split(' ', 1)[1] if p.note.startswith('`') else p.note}{near}"
        if c.kind == "duplicate_declaration":
            return f"`{c.text}` is declared more than once: {p.note}"
    if p.verdict == "supported":
        where = ", ".join(f"{l.path}:{l.line}" if l.line else l.path for l in p.locations)
        return f"Code {_CODE_WHAT.get(c.kind, 'names')} `{c.text}`; declared at {where}" if where else f"`{c.text}`; {p.note}"
    return f"Code {_CODE_WHAT.get(c.kind, 'names')} `{c.text}`; {p.note}"


def packet_remediation(p: EvidencePacket) -> str:
    if p.verdict != "contradicted":
        return ""
    if isinstance(p.claim, CodeClaim):
        c = p.claim
        if c.kind == "import_path":
            return f"Fix the specifier `{c.text}`" + (f" (nearest: {p.near[0]})" if p.near else "") + " or add the module."
        if c.kind == "duplicate_declaration":
            return f"Keep one declaration of `{c.name}` and re-export it from the others."
        if c.kind == "implements_signature":
            return f"Align `{c.subject}.{c.name}` with `{c.target}.{c.name}` or change the interface."
        return f"Declare `{c.name}`" + (f" (nearest: {p.near[0]})" if p.near else "") + " or remove the reference."
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
