"""Code claims: what one source file asserts about the rest of the repository.

A doc claim (claims_docs.py) is text that names an artifact; a code claim is
the same shape with code as the source: an import names a module, a member
access names a member of a declaration, ``implements`` names an interface
the class promises to satisfy, an object literal passed to a call names the
keys the callee's parameter type is expected to declare, and an exported
declaration claims to be the only one of its name. Every claim is compiled
from the language plugins' structure facts (osoji.plugins.base) and verified
against registries (factreg.py) -- no compiler, no model call.

Field names ``doc_path``/``line``/``text``/``name``/``kind`` are shared with
DocClaim so EvidencePacket and the audit read both without caring which.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

CODE_CLAIM_KINDS = (
    "import_path",            # a module specifier names a module in the tree
    "member_ref",             # `X.m` names a member of what X binds to
    "implements_member",      # a class declares every required member of the interface it implements
    "implements_signature",   # ...with the same required arity
    "call_arg_keys",          # an object literal argument's keys are declared by the callee's parameter type
    "duplicate_declaration",  # an exported declaration is the only one of its name and kind
)


@dataclass(frozen=True)
class CodeClaim:
    kind: str
    name: str                 # the thing claimed: resolved path, member, interface, key, declaration name
    doc_path: str             # the file making the claim (named doc_path for EvidencePacket/audit parity)
    line: int                 # 1-based
    text: str                 # as written: the specifier, `X.m`, `C implements I`, `f({ k })`, the declaration
    subject: str = ""         # class / object / callee / declaration kind
    target: str = ""          # interface / declared type / call member name
    arg_index: int = -1
    optional: bool = False    # `X.m?.()` / `X?.m`
    keys: tuple[str, ...] = field(default_factory=tuple)
    spread: bool = False
    call: bool = False        # the member access is invoked
    receiver: str | None = None        # call: the identifier the method is called on, "this", or None for a bare call
    enclosing_class: str | None = None  # call: the class whose body contains the call, for `this`
    ecosystem: str | None = None   # parity with DocClaim; code claims carry none


def _resolved_name(doc_path: str, specifier: str) -> str:
    if specifier.startswith("."):
        return posixpath.normpath(posixpath.join(posixpath.dirname(doc_path), specifier))
    return specifier


def extract_code_claims(structure: dict[str, dict]) -> list[CodeClaim]:
    claims: list[CodeClaim] = []
    by_name_kind: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for doc_path, facts in structure.items():
        seen: set[tuple] = set()

        def add(claim: CodeClaim) -> None:
            key = (claim.kind, claim.name, claim.line, claim.text, claim.arg_index)
            if key in seen:
                return
            seen.add(key)
            claims.append(claim)

        for imp in facts.get("imports", []):
            spec = imp.get("specifier") or ""
            if not spec:
                continue
            add(CodeClaim("import_path", _resolved_name(doc_path, spec), doc_path, int(imp.get("line") or 0), spec,
                          subject="reexport" if imp.get("reexport") else "import"))

        for ref in facts.get("member_refs", []):
            add(CodeClaim("member_ref", ref["member"], doc_path, int(ref.get("line") or 0),
                          f"{ref['object']}.{ref['member']}", subject=ref["object"],
                          optional=bool(ref.get("optional")), call=bool(ref.get("call"))))

        for decl in facts.get("declarations", []):
            if decl.get("kind") == "class":
                for iface in decl.get("implements") or []:
                    add(CodeClaim("implements_member", iface, doc_path, int(decl.get("line") or 0),
                                  f"{decl['name']} implements {iface}", subject=decl["name"], target=iface))
            if decl.get("exported") and decl.get("kind") in ("interface", "type", "enum", "class"):
                by_name_kind.setdefault((decl["name"], decl["kind"]), []).append((doc_path, decl))

        for call in facts.get("calls", []):
            member = call.get("member")
            if not member:
                continue
            for arg in call.get("args", []):
                keys = tuple(arg.get("keys") or [])
                if not keys and not arg.get("spread"):
                    continue
                add(CodeClaim("call_arg_keys", member, doc_path, int(call.get("line") or 0),
                              f"{member}({{ {', '.join(keys)} }})", subject=call.get("callee") or member,
                              target=member, arg_index=int(arg.get("index") or 0), keys=keys,
                              spread=bool(arg.get("spread")), receiver=call.get("receiver"),
                              enclosing_class=call.get("enclosing_class")))

    for (name, kind), decls in by_name_kind.items():
        if len({p for p, _ in decls}) < 2:
            continue
        for doc_path, decl in decls:
            claims.append(CodeClaim("duplicate_declaration", name, doc_path, int(decl.get("line") or 0),
                                    f"{kind} {name}", subject=kind))
    return claims
