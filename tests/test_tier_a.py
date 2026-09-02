"""Tests for the Tier A deterministic verifier."""

import json

from osoji.claims_docs import DocClaim
from osoji.config import Config
from osoji.factreg import PathRegistry, ScriptRegistry
from osoji.tier_a import EvidencePacket, packet_message, verify_doc_claims


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
