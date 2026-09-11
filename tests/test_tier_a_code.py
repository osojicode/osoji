"""Tier A on code claims: registries built from structure facts, no compiler, no LLM.

The structure facts here are hand-written in the language-neutral shape the
plugins emit (osoji.plugins.base.StructureFacts); nothing in these tests
needs Node. The scenarios mirror osoji-bench's code-consistency-697 rows.
"""

from __future__ import annotations

from osoji.claims_code import CodeClaim, extract_code_claims
from osoji.factreg import PathRegistry, SymbolRegistry
from osoji.tier_a import verify_code_claims


def _paths(*entries: str) -> PathRegistry:
    full: set[str] = set()
    for e in entries:
        full.add(e)
        parts = e.split("/")
        for i in range(1, len(parts)):
            full.add("/".join(parts[:i]))
    return PathRegistry(full)


def _ts_candidates(spec: str) -> list[str]:
    # the TypeScript plugin's ESM mapping, inlined so the tests stay Node-free
    if spec.endswith(".js"):
        base = spec[:-3]
        return [base + ".ts", base + ".tsx", base + ".d.ts", spec]
    if spec.endswith((".ts", ".tsx", ".mts", ".json")):
        return [spec]
    return [spec + ".ts", spec + ".tsx", spec + ".d.ts", spec + "/index.ts", spec + "/index.tsx"]


def _imp(spec, names, line=1, **kw):
    return {"specifier": spec, "names": names, "name_map": {}, "default": None, "namespace": None,
            "line": line, "reexport": False, "star": False, "type_only": False, **kw}


def _file(imports=(), declarations=(), member_refs=(), calls=(), local_exports=()):
    return {"imports": list(imports), "declarations": list(declarations), "member_refs": list(member_refs),
            "calls": list(calls), "local_exports": list(local_exports)}


def _verify(structure, paths, workspace=None):
    symbols = SymbolRegistry.from_structure(structure, module_candidates=_ts_candidates,
                                            workspace_packages=workspace or {}, paths=paths)
    claims = extract_code_claims(structure)
    return verify_code_claims(claims, paths, symbols, index_revision="t")


def _contradicted(packets, kind=None):
    return [p for p in packets if p.verdict == "contradicted" and (kind is None or p.claim.kind == kind)]


# --- import_path ------------------------------------------------------------


def test_relative_import_to_a_missing_module_is_contradicted():
    structure = {
        "tests/test-utils/mocks/mock-logger.ts": _file(imports=[_imp("../../src/interfaces/deps.js", ["ILogger"], line=5)]),
        "src/interfaces/deps.ts": _file(),
    }
    paths = _paths("tests/test-utils/mocks/mock-logger.ts", "src/interfaces/deps.ts")

    packets = _verify(structure, paths)

    (p,) = _contradicted(packets, "import_path")
    assert p.claim.doc_path == "tests/test-utils/mocks/mock-logger.ts" and p.claim.line == 5
    assert p.claim.name == "tests/src/interfaces/deps.js"          # where it resolves to
    assert p.claim.text == "../../src/interfaces/deps.js"          # as written
    assert "tests/src/interfaces/deps.ts" in p.searched[0] or any("tests/src" in s for s in p.searched)
    assert p.near == ["src/interfaces/deps.ts"]                    # the file one directory up


def test_relative_import_that_resolves_through_the_esm_mapping_is_supported():
    structure = {"src/a.ts": _file(imports=[_imp("./b.js", ["b"])]), "src/b.ts": _file()}
    packets = _verify(structure, _paths("src/a.ts", "src/b.ts"))
    (p,) = [p for p in packets if p.claim.kind == "import_path"]
    assert p.verdict == "supported" and p.locations[0].path == "src/b.ts"


def test_bare_specifier_is_undecidable_unless_it_is_a_workspace_package():
    structure = {
        "src/a.ts": _file(imports=[_imp("vitest", ["it"]), _imp("@acme/shared", ["Thing"]), _imp("@acme/shared/missing.js", ["X"])]),
        "packages/shared/src/index.ts": _file(),
    }
    paths = _paths("src/a.ts", "packages/shared/src/index.ts", "packages/shared/package.json")
    packets = _verify(structure, paths, workspace={"@acme/shared": "packages/shared/src"})
    by_text = {p.claim.text: p.verdict for p in packets if p.claim.kind == "import_path"}
    assert by_text == {"vitest": "undecidable", "@acme/shared": "supported", "@acme/shared/missing.js": "contradicted"}


def test_import_of_a_gitignored_generated_module_is_undecidable(monkeypatch):
    # codegen writes src/generated/schema.ts and the directory is gitignored:
    # the source form itself is ignored, so absence says nothing.
    structure = {"src/a.ts": _file(imports=[_imp("./generated/schema.js", ["Schema"])])}
    monkeypatch.setattr(PathRegistry, "gitignored", lambda self, names: [n for n in names if "generated" in n])
    (p,) = [p for p in _verify(structure, _paths("src/a.ts")) if p.claim.kind == "import_path"]
    assert p.verdict == "undecidable" and "gitignored" in p.note


def test_import_whose_only_ignored_candidates_are_build_artefacts_stays_contradicted(monkeypatch):
    # tests/**/*.js and tests/**/*.d.ts are compiled output of a .ts that does
    # not exist: the miss stands, at reduced confidence, naming the ignored forms.
    structure = {"tests/test-utils/mocks/m.ts": _file(imports=[_imp("../../src/x.js", ["x"])]), "src/x.ts": _file()}
    monkeypatch.setattr(PathRegistry, "gitignored",
                        lambda self, names: [n for n in names if n.endswith((".js", ".d.ts")) and n.startswith("tests/")])
    (p,) = _contradicted(_verify(structure, _paths("tests/test-utils/mocks/m.ts", "src/x.ts")), "import_path")
    assert p.grade == ("error", 0.8) and "tests/src/x.js" in p.note and "tests/src/x.ts is not" in p.note


def test_import_escaping_the_repository_is_undecidable():
    structure = {"src/a.ts": _file(imports=[_imp("../../elsewhere/x.js", ["x"])])}
    packets = _verify(structure, _paths("src/a.ts"))
    (p,) = [p for p in packets if p.claim.kind == "import_path"]
    assert p.verdict == "undecidable" and "outside" in p.note


# --- member_ref -------------------------------------------------------------


def _enum_world(member="IDLE"):
    return {
        "tests/policy.test.ts": _file(
            imports=[_imp("@acme/shared", ["SessionState"])],
            member_refs=[{"object": "SessionState", "member": member, "line": 191, "optional": False, "call": False}],
        ),
        "packages/shared/src/index.ts": _file(imports=[_imp("./models/index.js", ["*"], reexport=True, star=True)]),
        "packages/shared/src/models/index.ts": _file(declarations=[{
            "name": "SessionState", "kind": "enum", "exported": True, "line": 126, "open": False,
            "members": [{"name": n, "kind": "member"} for n in ("CREATED", "PAUSED", "STOPPED")],
        }]),
    }


_ENUM_PATHS = ("tests/policy.test.ts", "packages/shared/src/index.ts", "packages/shared/src/models/index.ts")


def test_enum_member_that_does_not_exist_is_contradicted_through_a_star_reexport():
    packets = _verify(_enum_world("IDLE"), _paths(*_ENUM_PATHS), workspace={"@acme/shared": "packages/shared/src"})
    (p,) = _contradicted(packets, "member_ref")
    assert p.claim.text == "SessionState.IDLE" and p.claim.line == 191
    assert p.locations[0].path == "packages/shared/src/models/index.ts"
    assert p.near == ["PAUSED", "CREATED", "STOPPED"] or set(p.near) <= {"CREATED", "PAUSED", "STOPPED"}
    assert p.grade == ("warning", 0.8)


def test_enum_member_that_exists_is_supported():
    packets = _verify(_enum_world("PAUSED"), _paths(*_ENUM_PATHS), workspace={"@acme/shared": "packages/shared/src"})
    (p,) = [p for p in packets if p.claim.kind == "member_ref"]
    assert p.verdict == "supported"


def test_member_access_on_an_unresolvable_or_open_object_is_undecidable():
    structure = {
        "src/a.ts": _file(
            imports=[_imp("vitest", ["vi"]), _imp("./b.js", ["cfg"])],
            member_refs=[
                {"object": "vi", "member": "fn", "line": 3, "optional": False, "call": True},          # external
                {"object": "cfg", "member": "nope", "line": 4, "optional": False, "call": False},     # variable, no shape
                {"object": "process", "member": "env", "line": 5, "optional": False, "call": False},  # unbound
            ],
        ),
        "src/b.ts": _file(declarations=[{"name": "cfg", "kind": "variable", "exported": True, "line": 1, "annotation": None}]),
    }
    packets = _verify(structure, _paths("src/a.ts", "src/b.ts"))
    refs = [p for p in packets if p.claim.kind == "member_ref"]
    assert refs and all(p.verdict == "undecidable" for p in refs)


def test_optional_hook_missing_from_an_object_literal_is_an_info_grade_contradiction():
    structure = {
        "tests/default.test.ts": _file(
            imports=[_imp("../src/policy.js", ["DefaultAdapterPolicy"])],
            member_refs=[{"object": "DefaultAdapterPolicy", "member": "updateStateOnCommand", "line": 27, "optional": True, "call": True},
                         {"object": "DefaultAdapterPolicy", "member": "name", "line": 6, "optional": False, "call": False}],
        ),
        "src/policy.ts": _file(declarations=[
            {"name": "AdapterPolicy", "kind": "interface", "exported": True, "line": 10, "extends": [], "open": False,
             "members": [{"name": "name", "kind": "property", "optional": False},
                         {"name": "updateStateOnCommand", "kind": "method", "optional": True, "params": 3, "required_params": 3}]},
            {"name": "DefaultAdapterPolicy", "kind": "object", "exported": True, "line": 735, "annotation": "AdapterPolicy",
             "open": False, "members": [{"name": "name", "kind": "property"}]},
        ]),
    }
    packets = _verify(structure, _paths("tests/default.test.ts", "src/policy.ts"))
    (p,) = _contradicted(packets, "member_ref")
    assert p.claim.text == "DefaultAdapterPolicy.updateStateOnCommand" and p.grade == ("info", 0.6)
    assert "optional" in p.note and "AdapterPolicy" in p.note
    assert [p.verdict for p in packets if p.claim.text == "DefaultAdapterPolicy.name"] == ["supported"]


def test_plain_read_of_an_absent_optional_member_is_undecidable():
    # `expect(CppAdapterPolicy.annotateOutputEvent).toBeUndefined()` reads the
    # absence on purpose; only a call that can never fire is dead.
    structure = {
        "tests/cpp.test.ts": _file(
            imports=[_imp("../src/policy.js", ["CppAdapterPolicy"])],
            member_refs=[{"object": "CppAdapterPolicy", "member": "annotateOutputEvent", "line": 88, "optional": False, "call": False}],
        ),
        "src/policy.ts": _file(declarations=[
            {"name": "AdapterPolicy", "kind": "interface", "exported": True, "line": 10, "extends": [], "open": False,
             "members": [{"name": "annotateOutputEvent", "kind": "method", "optional": True, "params": 1, "required_params": 1}]},
            {"name": "CppAdapterPolicy", "kind": "object", "exported": True, "line": 40, "annotation": "AdapterPolicy",
             "open": False, "members": [{"name": "name", "kind": "property"}]},
        ]),
    }
    (p,) = [p for p in _verify(structure, _paths("tests/cpp.test.ts", "src/policy.ts")) if p.claim.kind == "member_ref"]
    assert p.verdict == "undecidable" and "deliberate" in p.note


def test_shadowed_object_name_is_undecidable():
    # `function apply(config: Full) { return config.timeout }` next to a
    # module-level `config` literal: the identifier binds to the parameter.
    structure = {"src/a.ts": _file(
        declarations=[{"name": "config", "kind": "object", "exported": True, "line": 1, "annotation": None,
                       "open": False, "members": [{"name": "debug", "kind": "property"}]}],
        member_refs=[{"object": "config", "member": "timeout", "line": 4, "optional": False, "call": False, "shadowed": True},
                     {"object": "config", "member": "timeout", "line": 9, "optional": False, "call": False, "shadowed": False}],
    )}
    packets = [p for p in _verify(structure, _paths("src/a.ts")) if p.claim.kind == "member_ref"]
    assert [(p.claim.line, p.verdict) for p in packets] == [(4, "undecidable"), (9, "contradicted")]
    assert "enclosing scope" in packets[0].note


def test_object_literal_annotated_with_an_unresolvable_or_open_type_is_undecidable():
    # `const opts: RequestInit = { method: 'GET' }; opts.signal` -- the
    # annotation governs the shape and the registry cannot see it.
    structure = {
        "src/a.ts": _file(
            imports=[_imp("some-http-lib", ["RequestInit"]), _imp("./t.js", ["Open"])],
            declarations=[{"name": "opts", "kind": "object", "exported": False, "line": 2, "annotation": "RequestInit",
                           "open": False, "members": [{"name": "method", "kind": "property"}]},
                          {"name": "bag", "kind": "object", "exported": False, "line": 3, "annotation": "Open",
                           "open": False, "members": [{"name": "a", "kind": "property"}]}],
            member_refs=[{"object": "opts", "member": "signal", "line": 5, "optional": False, "call": False},
                         {"object": "bag", "member": "zzz", "line": 6, "optional": False, "call": False}],
        ),
        "src/t.ts": _file(declarations=[{"name": "Open", "kind": "interface", "exported": True, "line": 1, "extends": [],
                                         "open": True, "members": [{"name": "a", "kind": "property", "optional": False}]}]),
    }
    packets = [p for p in _verify(structure, _paths("src/a.ts", "src/t.ts")) if p.claim.kind == "member_ref"]
    assert [p.verdict for p in packets] == ["undecidable", "undecidable"]
    assert "does not resolve" in packets[0].note and "closed set" in packets[1].note


def test_member_ref_on_a_same_file_declaration_binds_without_an_import():
    structure = {"src/a.ts": _file(
        declarations=[{"name": "Colour", "kind": "enum", "exported": False, "line": 1, "open": False,
                       "members": [{"name": "RED", "kind": "member"}]}],
        member_refs=[{"object": "Colour", "member": "BLUE", "line": 9, "optional": False, "call": False}],
    )}
    (p,) = _contradicted(_verify(structure, _paths("src/a.ts")), "member_ref")
    assert p.claim.text == "Colour.BLUE"


# --- implements_member / implements_signature -------------------------------


def _implements_world(class_members, base="EventEmitter", iface_extends=("IProcess",)):
    return {
        "tests/start.test.ts": _file(
            imports=[_imp("../src/ifaces.js", ["IProxyProcess"]), _imp("events", ["EventEmitter"])],
            declarations=[{"name": "FakeProxyProcess", "kind": "class", "exported": False, "line": 14,
                           "extends": [base] if base else [], "implements": ["IProxyProcess"], "open": False,
                           "members": class_members}],
        ),
        "src/ifaces.ts": _file(declarations=[
            {"name": "IProcess", "kind": "interface", "exported": True, "line": 1, "extends": [], "open": False,
             "members": [{"name": "pid", "kind": "property", "optional": False},
                         {"name": "kill", "kind": "method", "optional": False, "params": 1, "required_params": 0}]},
            {"name": "IProxyProcess", "kind": "interface", "exported": True, "line": 55, "extends": list(iface_extends), "open": False,
             "members": [{"name": "sessionId", "kind": "property", "optional": False},
                         {"name": "sendCommand", "kind": "method", "optional": False, "params": 1, "required_params": 1},
                         {"name": "onProxyStatus", "kind": "method", "optional": False, "params": 2, "required_params": 2},
                         {"name": "extra", "kind": "property", "optional": True}]},
        ]),
    }


_IMPL_PATHS = ("tests/start.test.ts", "src/ifaces.ts")


def test_missing_required_member_is_undecidable_with_a_foreign_base():
    # v0 reported these at reduced confidence; 10 of 11 were members the
    # foreign base (EventEmitter) declares. An incomplete index is undecidable.
    members = [{"name": "pid", "kind": "property", "static": False},
               {"name": "kill", "kind": "method", "static": False, "params": 1, "required_params": 0},
               {"name": "sendCommand", "kind": "method", "static": False, "params": 1, "required_params": 1},
               {"name": "onProxyStatus", "kind": "method", "static": False, "params": 2, "required_params": 2}]
    packets = _verify(_implements_world(members), _paths(*_IMPL_PATHS))
    assert not _contradicted(packets, "implements_member")
    (p,) = [p for p in packets if p.claim.kind == "implements_member"]
    assert p.verdict == "undecidable" and p.claim.name == "sessionId" and "EventEmitter" in p.note


def test_missing_required_member_is_contradicted_when_the_base_chain_is_in_repo():
    members = [{"name": "pid", "kind": "property", "static": False},
               {"name": "kill", "kind": "method", "static": False, "params": 1, "required_params": 0},
               {"name": "sendCommand", "kind": "method", "static": False, "params": 1, "required_params": 1},
               {"name": "onProxyStatus", "kind": "method", "static": False, "params": 2, "required_params": 2}]
    packets = _verify(_implements_world(members, base=None), _paths(*_IMPL_PATHS))
    (p,) = _contradicted(packets, "implements_member")
    assert p.claim.text == "FakeProxyProcess implements IProxyProcess" and p.claim.name == "sessionId"
    assert p.claim.line == 14 and p.grade == ("error", 1.0)


def test_all_members_present_with_an_in_repo_base_is_supported_at_full_confidence():
    members = [{"name": "sessionId", "kind": "property", "static": False},
               {"name": "pid", "kind": "property", "static": False},
               {"name": "kill", "kind": "method", "static": False, "params": 1, "required_params": 0},
               {"name": "sendCommand", "kind": "method", "static": False, "params": 1, "required_params": 1},
               {"name": "onProxyStatus", "kind": "method", "static": False, "params": 2, "required_params": 2}]
    packets = _verify(_implements_world(members, base=None), _paths(*_IMPL_PATHS))
    kinds = {p.claim.kind: p.verdict for p in packets if p.claim.kind.startswith("implements")}
    assert kinds == {"implements_member": "supported"}
    assert not [p for p in packets if p.claim.kind == "implements_member" and p.verdict == "contradicted"]


def test_in_repo_base_class_in_another_file_supplies_inherited_members():
    # `class Fake extends Base implements IProxyProcess` where Base (another
    # file) declares pid/kill/sessionId: the extends walk must credit them.
    structure = _implements_world(
        [{"name": "sendCommand", "kind": "method", "static": False, "params": 1, "required_params": 1},
         {"name": "onProxyStatus", "kind": "method", "static": False, "params": 2, "required_params": 2}],
        base="Base",
    )
    structure["tests/start.test.ts"]["imports"].append(_imp("./base.js", ["Base"]))
    structure["tests/base.ts"] = _file(declarations=[{
        "name": "Base", "kind": "class", "exported": True, "line": 1, "extends": [], "implements": [], "open": False,
        "members": [{"name": "pid", "kind": "property", "static": False},
                    {"name": "sessionId", "kind": "property", "static": False},
                    {"name": "kill", "kind": "method", "static": False, "params": 1, "required_params": 0}],
    }])
    packets = _verify(structure, _paths(*_IMPL_PATHS, "tests/base.ts"))
    (p,) = [p for p in packets if p.claim.kind == "implements_member"]
    assert p.verdict == "supported"

    structure["tests/base.ts"]["declarations"][0]["members"].pop(1)      # Base loses sessionId
    packets = _verify(structure, _paths(*_IMPL_PATHS, "tests/base.ts"))
    (p,) = _contradicted(packets, "implements_member")
    assert p.claim.name == "sessionId" and p.grade == ("error", 1.0)


def test_narrower_implementation_signature_is_an_info_consistency_finding():
    members = [{"name": "sessionId", "kind": "property", "static": False},
               {"name": "pid", "kind": "property", "static": False},
               {"name": "kill", "kind": "method", "static": False, "params": 1, "required_params": 0},
               {"name": "sendCommand", "kind": "method", "static": False, "params": 1, "required_params": 1},
               {"name": "onProxyStatus", "kind": "method", "static": False, "params": 1, "required_params": 1}]
    packets = _verify(_implements_world(members, base=None), _paths(*_IMPL_PATHS))
    (p,) = _contradicted(packets, "implements_signature")
    assert p.claim.name == "onProxyStatus" and p.grade == ("info", 0.6)
    assert "1" in p.note and "2" in p.note


def test_unresolvable_interface_makes_the_implements_claim_undecidable():
    structure = {"src/a.ts": _file(
        imports=[_imp("some-lib", ["Thing"])],
        declarations=[{"name": "Impl", "kind": "class", "exported": True, "line": 3, "extends": [], "implements": ["Thing"],
                       "open": False, "members": []}],
    )}
    packets = _verify(structure, _paths("src/a.ts"))
    (p,) = [p for p in packets if p.claim.kind == "implements_member"]
    assert p.verdict == "undecidable"


# --- call_arg_keys ----------------------------------------------------------


def _call_world(decls_in_store, key="pythonPath", receiver="sessionManager", locals_=None):
    f = _file(
        imports=[_imp("../src/store.js", ["SessionManager"])],
        calls=[{"callee": f"{receiver}.createSession", "member": "createSession", "line": 36, "receiver": receiver,
                "enclosing_class": None, "args": [{"index": 0, "keys": ["language", key], "spread": False}]}],
    )
    f["locals"] = locals_ if locals_ is not None else [{"name": "sessionManager", "type": "SessionManager", "line": 10, "kind": "local"}]
    return {"tests/paths.test.ts": f, "src/store.ts": _file(declarations=decls_in_store)}


_PARAMS_DECL = {"name": "CreateSessionParams", "kind": "interface", "exported": True, "line": 80, "extends": [], "open": False,
                "members": [{"name": "language", "kind": "property", "optional": False},
                            {"name": "executablePath", "kind": "property", "optional": True}]}


def _store_class(param_type="CreateSessionParams", members=None, open_=False, name="SessionManager"):
    return {"name": name, "kind": "class", "exported": True, "line": 100, "extends": [], "implements": [], "open": False,
            "members": [{"name": "createSession", "kind": "method", "static": False, "params": 1, "required_params": 1, "line": 102,
                         "param_list": [{"name": "params", "optional": False, "rest": False, "type": param_type,
                                         "members": members, "open": open_}]}]}


def test_object_key_absent_from_the_receivers_declared_parameter_type_is_contradicted():
    packets = _verify(_call_world([_PARAMS_DECL, _store_class()]), _paths("tests/paths.test.ts", "src/store.ts"))
    (p,) = _contradicted(packets, "call_arg_keys")
    assert p.claim.text == "createSession({ pythonPath })" and p.claim.name == "pythonPath" and p.claim.line == 36
    assert p.grade == ("warning", 0.7)
    assert p.locations[0].path == "src/store.ts" and p.locations[0].line == 102
    assert "executablePath" in p.near


def test_key_declared_by_the_parameter_type_is_supported_and_open_types_are_undecidable():
    inline = _store_class(param_type=None, members=["language", "pythonPath"])
    packets = _verify(_call_world([_PARAMS_DECL, inline]), _paths("tests/paths.test.ts", "src/store.ts"))
    assert [p.verdict for p in packets if p.claim.kind == "call_arg_keys"] == ["supported"]

    open_decl = _store_class(param_type=None, members=None, open_=True)
    packets = _verify(_call_world([_PARAMS_DECL, open_decl]), _paths("tests/paths.test.ts", "src/store.ts"))
    assert [p.verdict for p in packets if p.claim.kind == "call_arg_keys"] == ["undecidable"]


def test_callee_is_never_resolved_by_name_alone():
    # v0 bound `cache.set({...})` to an unrelated in-repo `set(...)` by name: 156 false
    # positives. Without a typed receiver the claim is undecidable.
    untyped = _call_world([_PARAMS_DECL, _store_class()], locals_=[])
    packets = _verify(untyped, _paths("tests/paths.test.ts", "src/store.ts"))
    (p,) = [p for p in packets if p.claim.kind == "call_arg_keys"]
    assert p.verdict == "undecidable" and "sessionManager" in p.note

    other_class = _call_world([_PARAMS_DECL, _store_class(name="SessionStore")])   # receiver typed SessionManager, no such class
    packets = _verify(other_class, _paths("tests/paths.test.ts", "src/store.ts"))
    assert [p.verdict for p in packets if p.claim.kind == "call_arg_keys"] == ["undecidable"]

    structure = _call_world([_PARAMS_DECL, _store_class()])
    structure["tests/paths.test.ts"]["calls"][0]["args"][0]["spread"] = True
    packets = _verify(structure, _paths("tests/paths.test.ts", "src/store.ts"))
    assert [p.verdict for p in packets if p.claim.kind == "call_arg_keys"] == ["undecidable"]


def test_bare_call_binds_the_function_and_this_binds_the_enclosing_class():
    structure = {
        "src/a.ts": _file(
            imports=[_imp("./b.js", ["build"])],
            declarations=[{"name": "Server", "kind": "class", "exported": True, "line": 5, "extends": [], "implements": [], "open": False,
                           "members": [{"name": "configure", "kind": "method", "static": False, "params": 1, "required_params": 1, "line": 6,
                                        "param_list": [{"name": "o", "optional": False, "rest": False, "type": None, "members": ["port"], "open": False}]}]}],
            calls=[{"callee": "build", "member": "build", "receiver": None, "enclosing_class": None, "line": 20,
                    "args": [{"index": 0, "keys": ["target", "verbose"], "spread": False}]},
                   {"callee": "this.configure", "member": "configure", "receiver": "this", "enclosing_class": "Server", "line": 9,
                    "args": [{"index": 0, "keys": ["port", "host"], "spread": False}]}],
        ),
        "src/b.ts": _file(declarations=[{"name": "build", "kind": "function", "exported": True, "line": 1, "required_params": 1,
                                         "params": [{"name": "o", "optional": False, "rest": False, "type": None, "members": ["target"], "open": False}]}]),
    }
    packets = _contradicted(_verify(structure, _paths("src/a.ts", "src/b.ts")), "call_arg_keys")
    assert sorted((p.claim.target, p.claim.name) for p in packets) == [("build", "verbose"), ("configure", "host")]


# --- duplicate_declaration --------------------------------------------------


def _iface(name, members, line=1):
    return {"name": name, "kind": "interface", "exported": True, "line": line, "extends": [], "open": False,
            "members": [{"name": m, "kind": "property", "optional": False} for m in members]}


def test_duplicate_exported_declarations_with_overlapping_members_are_reported_once_per_copy():
    structure = {
        "a/deps.ts": _file(declarations=[_iface("IFileSystem", ["readFile", "writeFile", "exists", "mkdir"], 21)]),
        "b/deps.ts": _file(declarations=[_iface("IFileSystem", ["readFile", "writeFile", "exists", "mkdir"], 17)]),
        "c/proxy.ts": _file(declarations=[_iface("IFileSystem", ["readFile", "exists", "remove"], 179)]),
        "d/other.ts": _file(declarations=[_iface("Options", ["verbose"]), ]),
        "e/other.ts": _file(declarations=[_iface("Options", ["port", "host", "timeout"]), ]),
    }
    packets = _verify(structure, _paths("a/deps.ts", "b/deps.ts", "c/proxy.ts", "d/other.ts", "e/other.ts"))
    dups = _contradicted(packets, "duplicate_declaration")
    assert sorted(p.claim.doc_path for p in dups) == ["a/deps.ts", "b/deps.ts", "c/proxy.ts"]
    by_file = {p.claim.doc_path: p for p in dups}
    assert by_file["c/proxy.ts"].grade == ("warning", 0.7) and "diverged" in by_file["c/proxy.ts"].note
    assert by_file["a/deps.ts"].grade == ("info", 0.5)
    assert by_file["c/proxy.ts"].claim.line == 179
    assert not [p for p in dups if p.claim.name == "Options"]   # homonyms: not copies


# --- claims ------------------------------------------------------------------


def test_extract_code_claims_carries_the_doc_path_line_and_text_the_audit_reads():
    structure = {"src/a.ts": _file(imports=[_imp("./b.js", ["b"], line=2)])}
    (c,) = extract_code_claims(structure)
    assert isinstance(c, CodeClaim)
    assert (c.kind, c.doc_path, c.line, c.text, c.name) == ("import_path", "src/a.ts", 2, "./b.js", "src/b.js")
