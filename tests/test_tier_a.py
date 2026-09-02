"""Tests for the Tier A deterministic verifier."""

import json

from osoji.claims_docs import DocClaim
from osoji.config import Config
from osoji.factreg import PathRegistry, ScriptRegistry
from osoji.tier_a import EvidencePacket, packet_message, packet_remediation, verify_doc_claims


def _setup(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"test": "vitest", "test:unit": "vitest run"}}), encoding="utf-8")
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "server.ts").write_text("export {}\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    return PathRegistry.from_config(config), ScriptRegistry.from_config(config)


def _claim(kind, name, eco=None):
    return DocClaim(kind=kind, name=name, doc_path="README.md", line=7, text=name, ecosystem=eco, in_fence=False)


def test_missing_script_is_contradicted_with_namespace_and_near_matches(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("script_exists", "test:ui", "npm")], paths, scripts, index_revision="abc123")

    assert packet.verdict == "contradicted"
    assert packet.namespace == "scripts"
    assert packet.searched == ["package.json#scripts"]
    assert "test:unit" in packet.near
    assert packet.index_revision == "abc123"
    msg = packet_message(packet)
    assert "test:ui" in msg and "package.json#scripts" in msg and "test:unit" in msg


def test_present_script_and_path_are_supported_with_locations(temp_dir):
    paths, scripts = _setup(temp_dir)
    packets = verify_doc_claims(
        [_claim("script_exists", "test:unit", "npm"), _claim("path_exists", "src/server.ts")], paths, scripts
    )
    assert [p.verdict for p in packets] == ["supported", "supported"]
    assert packets[0].locations[0].path == "package.json"
    assert packets[1].locations[0].path == "src/server.ts"


def test_missing_path_is_contradicted(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("path_exists", "src/servr.ts")], paths, scripts)
    assert packet.verdict == "contradicted"
    assert "src/server.ts" in packet.near


def test_script_claim_without_manifest_is_undecidable(temp_dir):
    (temp_dir / "README.md").write_text("x\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)
    (packet,) = verify_doc_claims([_claim("script_exists", "build", "npm")], paths, scripts)
    assert packet.verdict == "undecidable"
    assert packet.searched == []


def test_packet_serializes_to_plain_dict(temp_dir):
    paths, scripts = _setup(temp_dir)
    (packet,) = verify_doc_claims([_claim("script_exists", "test:ui", "npm")], paths, scripts)
    d = packet.to_dict()
    assert d["claim"]["name"] == "test:ui" and d["verdict"] == "contradicted"
    assert isinstance(d["searched"], list) and isinstance(d["near"], list)
    json.dumps(d)  # must be JSON-serializable


def test_path_claim_inside_an_ignored_prefix_is_undecidable_not_contradicted(temp_dir):
    """Global constraint 3, applied to paths: an absent namespace never contradicts.

    ``.github`` is in DEFAULT_IGNORE_PATTERNS, so the registry never indexes
    the workflow even though git tracks it. Reporting `contradicted` here is a
    commission error against a file that demonstrably exists.
    """
    (temp_dir / ".github" / "workflows").mkdir(parents=True)
    (temp_dir / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (temp_dir / "README.md").write_text("x\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)

    (packet,) = verify_doc_claims([_claim("path_exists", ".github/workflows/ci.yml")], paths, scripts)

    assert packet.verdict == "undecidable"
    assert ".github" in packet.note
    assert "manifest" not in packet.note  # the script registry's note, not this one
    assert packet_message(packet).endswith(packet.note)


def test_undecidable_path_claim_carries_no_remediation(temp_dir):
    from osoji.tier_a import packet_remediation

    (temp_dir / "node_modules").mkdir()
    (temp_dir / "node_modules" / "dep.js").write_text("x\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)

    (packet,) = verify_doc_claims([_claim("path_exists", "node_modules/dep.js")], paths, scripts)

    assert packet.verdict == "undecidable"
    assert packet_remediation(packet) == ""


def test_unanchored_path_claim_is_undecidable_not_contradicted(temp_dir):
    """The anchor rule at the verifier: `tools/list` is an RPC method, not a path."""
    paths, scripts = _setup(temp_dir)

    packets = verify_doc_claims(
        [_claim("path_exists", "tools/list"), _claim("path_exists", "src/nope.ts")], paths, scripts
    )

    assert [p.verdict for p in packets] == ["undecidable", "contradicted"]
    assert packets[0].note == "root segment not in the tree; not a repo-relative claim"


def test_creation_modality_path_claim_is_undecidable(temp_dir):
    """"Create `src/handlers/new_tool.ts` with:" asserts nothing about the tree."""
    paths, scripts = _setup(temp_dir)
    claim = DocClaim(kind="path_exists", name="src/handlers/new_tool.ts", doc_path="README.md",
                     line=7, text="src/handlers/new_tool.ts", ecosystem=None, in_fence=False,
                     modality="creation")

    (packet,) = verify_doc_claims([claim], paths, scripts)

    assert packet.verdict == "undecidable"
    assert packet.note == "creation instruction, existence not asserted"
    assert packet_remediation(packet) == ""


def test_creation_modality_is_undecidable_even_when_the_path_exists(temp_dir):
    """The guard is about what the line asserts, not about what the tree holds.

    A "create it" line makes no existence claim either way, so the verdict is
    the same whether or not the artifact happens to be there. Nothing is lost
    downstream: only `contradicted` packets become findings.
    """
    paths, scripts = _setup(temp_dir)
    claim = DocClaim(kind="path_exists", name="src/server.ts", doc_path="README.md", line=7,
                     text="src/server.ts", ecosystem=None, in_fence=False, modality="creation")

    (packet,) = verify_doc_claims([claim], paths, scripts)

    assert packet.verdict == "undecidable"


# --- rulings wave: bare package-manager words --------------------------------


def _verify_line(temp_dir, line, scripts_declared):
    from osoji.claims_docs import extract_doc_claims

    (temp_dir / "package.json").write_text(json.dumps({"scripts": scripts_declared}), encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)
    claims = [c for c in extract_doc_claims("README.md", line) if c.kind == "script_exists"]
    return verify_doc_claims(claims, paths, scripts)


def test_bare_package_manager_word_without_a_matching_script_is_undecidable(temp_dir):
    """`pnpm vitest` may be a node_modules/.bin binary the registry never sees."""
    (packet,) = _verify_line(temp_dir, "Run `pnpm vitest`.\n", {"build": "tsc"})

    assert packet.verdict == "undecidable"
    assert packet.note == "bare package-manager word may be a binary, not a script"


def test_explicit_run_form_stays_decidable(temp_dir):
    """`pnpm run vitest` can only mean a declared script, so absence contradicts."""
    (packet,) = _verify_line(temp_dir, "Run `pnpm run vitest`.\n", {"build": "tsc"})

    assert packet.verdict == "contradicted"


def test_bare_package_manager_word_that_is_a_declared_script_is_supported(temp_dir):
    (packet,) = _verify_line(temp_dir, "Run `pnpm test:e2e`.\n", {"test:e2e": "playwright"})

    assert packet.verdict == "supported"
    assert packet.locations[0].path == "package.json"


def test_bare_alias_word_is_still_contradicted_when_no_script_declares_it(temp_dir):
    """`pnpm test` is a `run` alias, not a binary lookup -- absence contradicts."""
    (packet,) = _verify_line(temp_dir, "Run `pnpm test`.\n", {"build": "tsc"})

    assert packet.verdict == "contradicted"


# --- rulings fix wave: doc-relative resolution --------------------------------


def _verify_doc(temp_dir, doc_path, line, files):
    """Write `files` under temp_dir, then run the real extract -> verify pipeline."""
    from osoji.claims_docs import extract_doc_claims

    for rel, content in files.items():
        p = temp_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    paths, scripts = PathRegistry.from_config(config), ScriptRegistry.from_config(config)
    claims = [c for c in extract_doc_claims(doc_path, line) if c.kind == "path_exists"]
    return verify_doc_claims(claims, paths, scripts)


def test_dot_relative_link_resolves_against_the_doc_directory_first(temp_dir):
    """docs/guide.md naming `./api.md`, with docs/api.md present -> supported."""
    (packet,) = _verify_doc(
        temp_dir, "docs/guide.md",
        "See [the API doc](./api.md) for details.\n",
        {"docs/guide.md": "x\n", "docs/api.md": "# API\n"},
    )

    assert packet.verdict == "supported"
    assert packet.locations[0].path == "docs/api.md"


def test_dot_relative_link_to_a_missing_doc_sibling_is_contradicted(temp_dir):
    """Same doc, `./api.md` absent but docs/ is real -> contradicted, doc-relative candidate noted."""
    (packet,) = _verify_doc(
        temp_dir, "docs/guide.md",
        "See [the API doc](./api.md) for details.\n",
        {"docs/guide.md": "x\n"},
    )

    assert packet.verdict == "contradicted"
    assert "docs/api.md" in packet.note
    assert "resolved relative to docs" in packet.note


def test_plain_token_falls_back_to_doc_relative_resolution(temp_dir):
    """docs/guide.md naming `src/x.ts`, only docs/src/x.ts exists -> supported (fallback)."""
    (packet,) = _verify_doc(
        temp_dir, "docs/guide.md",
        "See `src/x.ts` for the implementation.\n",
        {"docs/guide.md": "x\n", "docs/src/x.ts": "export {}\n"},
    )

    assert packet.verdict == "supported"
    assert packet.locations[0].path == "docs/src/x.ts"
    assert "resolved relative to docs" in packet.note


def test_root_relative_resolution_still_works_from_a_nested_doc(temp_dir):
    """docs/guide.md naming `src/server.ts`, which exists at the repo root -> supported."""
    (packet,) = _verify_doc(
        temp_dir, "docs/guide.md",
        "See `src/server.ts` for the entry point.\n",
        {"docs/guide.md": "x\n", "src/server.ts": "export {}\n"},
    )

    assert packet.verdict == "supported"
    assert packet.locations[0].path == "src/server.ts"
    assert packet.note == ""


def test_foreign_looking_token_in_a_nested_doc_stays_undecidable(temp_dir):
    """Signal conservation: doc-relative fallback must not anchor a foreign token.

    `src/dapDebugServer.js` names another project's layout on the line; there
    is no `src/` at the repo root and no `docs/src/` under this doc's own
    directory either, so neither candidate is anchored -- the claim must stay
    undecidable, not be promoted to `contradicted` just because `docs/`
    itself is real.
    """
    (packet,) = _verify_doc(
        temp_dir, "docs/architecture/README.md",
        "Upstream js-debug lays out `src/dapDebugServer.js` for its transport.\n",
        {"docs/architecture/README.md": "x\n"},
    )

    assert packet.verdict == "undecidable"


def test_markdown_link_without_a_dot_prefix_is_still_doc_relative(temp_dir):
    """A markdown link target is doc-relative by convention, dot-prefix or not."""
    (packet,) = _verify_doc(
        temp_dir, "docs/guide.md",
        "See [the sub doc](sub/foo.md) for details.\n",
        {"docs/guide.md": "x\n"},
    )

    assert packet.verdict == "contradicted"
    assert "resolved relative to docs" in packet.note
