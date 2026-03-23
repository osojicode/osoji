"""Tests for the observatory export bundle."""

import json
from pathlib import Path

import jsonschema
import pytest
from click.testing import CliRunner

import osoji
from osoji.cli import main
from osoji.hasher import compute_hash, compute_impl_hash
from osoji.observatory import (
    OBSERVATORY_SCHEMA_NAME,
    OBSERVATORY_SCHEMA_VERSION,
    build_observatory_bundle,
)

_SCHEMA_PATH = Path(osoji.__file__).parent / "osoji-observatory.schema.json"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _write_source(root: Path, rel_path: str, content: str = "x = 1\n") -> Path:
    full = root / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def _write_shadow(
    root: Path,
    rel_path: str,
    content: str | None = None,
    *,
    source_hash: str | None = None,
    impl_hash: str | None = None,
) -> Path:
    shadow_dir = root / ".osoji" / "shadow"
    shadow_file = shadow_dir / (rel_path + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = f"# {rel_path}\n"
        if source_hash:
            content = f"# {rel_path}\n@source-hash: {source_hash}\n"
            if impl_hash:
                content += f"@impl-hash: {impl_hash}\n"
    shadow_file.write_text(content, encoding="utf-8")
    return shadow_file


def _write_findings(root: Path, rel_path: str, findings: list[dict]) -> Path:
    from osoji.hasher import compute_file_hash
    findings_dir = root / ".osoji" / "findings"
    findings_file = findings_dir / (rel_path + ".findings.json")
    findings_file.parent.mkdir(parents=True, exist_ok=True)
    source_path = root / rel_path
    source_hash = compute_file_hash(source_path) if source_path.exists() else "no-source"
    findings_file.write_text(
        json.dumps(
            {
                "source": rel_path,
                "source_hash": source_hash,
                "impl_hash": compute_impl_hash(),
                "generated": "2026-03-10T00:00:00Z",
                "findings": findings,
            }
        ),
        encoding="utf-8",
    )
    return findings_file


def _write_symbols(root: Path, rel_path: str, symbols: list[dict], file_role: str | None = None) -> Path:
    symbols_dir = root / ".osoji" / "symbols"
    symbols_file = symbols_dir / (rel_path + ".symbols.json")
    symbols_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": rel_path,
        "source_hash": "abc123",
        "generated": "2026-03-10T00:00:00Z",
        "symbols": symbols,
    }
    if file_role is not None:
        payload["file_role"] = file_role
    symbols_file.write_text(json.dumps(payload), encoding="utf-8")
    return symbols_file


def _write_signature(root: Path, rel_path: str, purpose: str, topics: list[str]) -> Path:
    signatures_dir = root / ".osoji" / "signatures"
    signature_file = signatures_dir / (rel_path + ".signature.json")
    signature_file.parent.mkdir(parents=True, exist_ok=True)
    signature_file.write_text(
        json.dumps(
            {
                "path": rel_path,
                "kind": "source",
                "purpose": purpose,
                "topics": topics,
                "public_surface": [],
            }
        ),
        encoding="utf-8",
    )
    return signature_file


def _write_token_cache(root: Path, entries: dict) -> Path:
    token_cache = root / ".osoji" / "token-cache.json"
    token_cache.parent.mkdir(parents=True, exist_ok=True)
    token_cache.write_text(json.dumps(entries), encoding="utf-8")
    return token_cache


def _write_audit_result(root: Path, issues: list[dict], scorecard: dict | None = None) -> Path:
    analysis_root = root / ".osoji" / "analysis"
    audit_result = analysis_root / "audit-result.json"
    analysis_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "passed": not any(issue.get("severity") == "error" for issue in issues),
        "errors": sum(1 for issue in issues if issue.get("severity") == "error"),
        "warnings": sum(1 for issue in issues if issue.get("severity") == "warning"),
        "infos": sum(1 for issue in issues if issue.get("severity") == "info"),
        "issues": issues,
    }
    if scorecard is not None:
        payload["scorecard"] = scorecard
    audit_result.write_text(json.dumps(payload), encoding="utf-8")
    return audit_result


def _find_file_node(tree: dict, *segments: str) -> dict:
    node = tree
    for segment in segments:
        node = next(child for child in node["children"] if child["name"] == segment)
    return node


def test_build_bundle_maps_audit_findings_and_normalizes_paths(temp_dir):
    content = "def run():\n    return 1\n"
    _write_source(temp_dir, "src/pkg/mod.py", content)
    _write_shadow(
        temp_dir,
        "src/pkg/mod.py",
        source_hash=compute_hash(content),
        impl_hash=compute_impl_hash(),
    )
    _write_findings(
        temp_dir,
        "src/pkg/mod.py",
        [
            {
                "category": "dead_code",
                "severity": "warning",
                "line_start": 1,
                "line_end": 1,
                "description": "Old helper",
            }
        ],
    )
    _write_symbols(
        temp_dir,
        "src/pkg/mod.py",
        [
            {
                "name": "run",
                "kind": "function",
                "line_start": 1,
                "line_end": 2,
                "visibility": "public",
            }
        ],
        file_role="service",
    )
    _write_signature(temp_dir, "src/pkg/mod.py", "Runs the package flow", ["execution", "orchestration"])
    _write_token_cache(
        temp_dir,
        {
            "src/pkg/mod.py": {
                "source_tokens": 100,
                "shadow_tokens": 40,
            }
        },
    )
    _write_audit_result(
        temp_dir,
        [
            {
                "path": "src\\pkg\\mod.py",
                "severity": "warning",
                "category": "dead_code",
                "message": "Unused branch",
                "remediation": "Delete the branch",
                "line_start": 4,
                "line_end": 7,
            },
            {
                "path": "src\\pkg\\mod.py",
                "severity": "error",
                "category": "latent_bug",
                "message": "Null dereference",
                "remediation": "Guard the access",
                "line_start": 2,
                "line_end": 2,
            },
        ],
        scorecard={"coverage_pct": 50.0},
    )

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert bundle["schema_name"] == OBSERVATORY_SCHEMA_NAME
    assert bundle["schema_version"] == OBSERVATORY_SCHEMA_VERSION
    assert bundle["audit_status"] == "present"
    assert bundle["project"]["name"] == temp_dir.name
    assert bundle["metrics"]["file_count"] == 1
    assert bundle["tokens"]["source_tokens"] == 100
    assert bundle["tokens"]["shadow_tokens"] == 40
    assert bundle["scorecard"]["coverage_pct"] == 50.0

    file_node = _find_file_node(bundle["tree"], "src", "pkg", "mod.py")
    assert file_node["path"] == "src/pkg/mod.py"
    assert file_node["shadow"]["exists"] is True
    assert file_node["shadow"]["is_stale"] is False
    assert file_node["symbols"]["count"] == 1
    assert file_node["symbols"]["public_count"] == 1
    assert file_node["symbols"]["file_role"] == "service"
    assert file_node["signature"]["purpose"] == "Runs the package flow"
    assert file_node["metrics"]["findings_count"] == 1
    assert file_node["metrics"]["audit_findings_count"] == 2
    assert file_node["audit_findings"][0]["severity"] == "error"
    assert file_node["audit_findings"][0]["line_start"] == 2
    assert file_node["audit_findings"][1]["severity"] == "warning"


def test_build_bundle_marks_audit_missing_when_no_cached_audit(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert bundle["audit_status"] == "missing"
    file_node = _find_file_node(bundle["tree"], "main.py")
    assert file_node["audit_findings"] == []
    assert file_node["metrics"]["audit_findings_count"] == 0


def _write_facts(root: Path, rel_path: str, facts_data: dict) -> Path:
    facts_dir = root / ".osoji" / "facts"
    facts_file = facts_dir / (rel_path + ".facts.json")
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    facts_file.write_text(json.dumps(facts_data), encoding="utf-8")
    return facts_file


def _write_doc_analysis(root: Path, doc_rel_path: str, analysis: dict) -> Path:
    analysis_file = root / ".osoji" / "analysis" / "docs" / (doc_rel_path + ".analysis.json")
    analysis_file.parent.mkdir(parents=True, exist_ok=True)
    analysis_file.write_text(json.dumps(analysis), encoding="utf-8")
    return analysis_file


def test_bundle_includes_import_graph_from_facts(temp_dir):
    _write_source(temp_dir, "src/a.py", "from .b import Foo\n")
    _write_source(temp_dir, "src/b.py", "class Foo: pass\n")
    _write_facts(temp_dir, "src/a.py", {
        "source": "src/a.py",
        "source_hash": "abc",
        "imports": [{"source": ".b", "names": ["Foo"]}],
        "exports": [],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
    })
    _write_facts(temp_dir, "src/b.py", {
        "source": "src/b.py",
        "source_hash": "def",
        "imports": [],
        "exports": [{"name": "Foo", "kind": "class", "line": 1}],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
    })

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert "import_graph" in bundle
    edges = bundle["import_graph"]
    assert len(edges) == 1
    assert edges[0]["source"] == "src/a.py"
    assert edges[0]["target"] == "src/b.py"
    assert "Foo" in edges[0]["names"]


def test_bundle_import_graph_empty_when_no_facts(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert bundle["import_graph"] == []


def test_bundle_file_nodes_include_facts_summary(temp_dir):
    _write_source(temp_dir, "src/mod.py", "from .util import helper\nhelper()\n")
    _write_source(temp_dir, "src/util.py", "def helper(): pass\n")
    _write_facts(temp_dir, "src/mod.py", {
        "source": "src/mod.py",
        "source_hash": "abc",
        "imports": [{"source": ".util", "names": ["helper"]}],
        "exports": [],
        "calls": [{"from_symbol": "top_level", "to": "helper", "line": 2}],
        "member_writes": [],
        "string_literals": [],
    })
    _write_facts(temp_dir, "src/util.py", {
        "source": "src/util.py",
        "source_hash": "def",
        "imports": [],
        "exports": [{"name": "helper", "kind": "function", "line": 1}],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
    })

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    mod_node = _find_file_node(bundle["tree"], "src", "mod.py")
    assert mod_node["facts_summary"] is not None
    assert len(mod_node["facts_summary"]["imports"]) == 1
    assert mod_node["facts_summary"]["imports"][0]["names"] == ["helper"]
    assert len(mod_node["facts_summary"]["calls"]) == 1
    assert mod_node["facts_summary"]["calls"][0]["to"] == "helper"

    util_node = _find_file_node(bundle["tree"], "src", "util.py")
    assert util_node["facts_summary"] is not None
    assert len(util_node["facts_summary"]["exports"]) == 1
    assert util_node["facts_summary"]["exports"][0]["name"] == "helper"


def test_bundle_facts_summary_none_when_no_facts(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    file_node = _find_file_node(bundle["tree"], "main.py")
    assert file_node["facts_summary"] is None


def test_bundle_includes_doc_analysis(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")
    _write_doc_analysis(temp_dir, "README.md", {
        "classification": "reference",
        "confidence": 0.95,
        "matched_shadows": ["main.py"],
        "findings": [{"category": "stale_content", "severity": "warning", "description": "Outdated info"}],
        "topic_signature": {"purpose": "Overview of project", "topics": ["CLI", "setup"]},
    })

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert "doc_analysis" in bundle
    assert "README.md" in bundle["doc_analysis"]
    analysis = bundle["doc_analysis"]["README.md"]
    assert analysis["classification"] == "reference"
    assert analysis["confidence"] == 0.95
    assert analysis["purpose"] == "Overview of project"
    assert analysis["topics"] == ["CLI", "setup"]
    assert analysis["matched_sources"] == ["main.py"]
    assert analysis["accuracy_error_count"] == 1
    assert len(analysis["findings"]) == 1
    assert analysis["findings"][0]["description"] == "Outdated info"


def test_bundle_doc_analysis_empty_when_no_docs(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert bundle["doc_analysis"] == {}


def test_bundle_schema_version_is_1_2_0(temp_dir):
    _write_source(temp_dir, "main.py", "x = 1\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    assert bundle["schema_version"] == "1.2.0"


def test_export_command_writes_bundle_file(temp_dir):
    _write_source(temp_dir, "main.py", "print('hi')\n")
    output_path = temp_dir / "bundle.json"

    runner = CliRunner()
    result = runner.invoke(main, ["export", str(temp_dir), "--output", str(output_path)])

    assert result.exit_code == 0
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema_name"] == OBSERVATORY_SCHEMA_NAME
    assert payload["schema_version"] == OBSERVATORY_SCHEMA_VERSION


# --- Schema validation tests ---


def test_schema_file_is_valid_json():
    schema = _load_schema()
    assert "$schema" in schema
    assert "$defs" in schema
    assert "properties" in schema
    jsonschema.Draft202012Validator.check_schema(schema)


def test_minimal_bundle_validates_against_schema(temp_dir):
    _write_source(temp_dir, "main.py", "x = 1\n")

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)
    schema = _load_schema()
    jsonschema.validate(instance=bundle, schema=schema)


def test_full_bundle_validates_against_schema(temp_dir):
    content = "def run():\n    return 1\n"
    _write_source(temp_dir, "src/mod.py", content)
    _write_shadow(
        temp_dir,
        "src/mod.py",
        source_hash=compute_hash(content),
        impl_hash=compute_impl_hash(),
    )
    _write_findings(
        temp_dir,
        "src/mod.py",
        [
            {
                "category": "dead_code",
                "severity": "warning",
                "line_start": 1,
                "line_end": 1,
                "description": "Old helper",
            }
        ],
    )
    _write_symbols(
        temp_dir,
        "src/mod.py",
        [{"name": "run", "kind": "function", "line_start": 1, "line_end": 2, "visibility": "public"}],
    )
    _write_signature(temp_dir, "src/mod.py", "Runs flow", ["execution"])
    _write_token_cache(temp_dir, {"src/mod.py": {"source_tokens": 100, "shadow_tokens": 40}})
    _write_facts(temp_dir, "src/mod.py", {
        "source": "src/mod.py",
        "source_hash": "abc",
        "imports": [],
        "exports": [{"name": "run", "kind": "function", "line": 1}],
        "calls": [],
        "member_writes": [],
        "string_literals": [],
    })
    _write_doc_analysis(temp_dir, "README.md", {
        "classification": "reference",
        "confidence": 0.95,
        "matched_shadows": ["src/mod.py"],
        "findings": [],
        "topic_signature": {"purpose": "Overview", "topics": ["CLI"]},
    })
    scorecard = {
        "coverage_entries": [],
        "coverage_pct": 100.0,
        "covered_count": 1,
        "total_source_count": 1,
        "coverage_by_type": {},
        "type_covered_counts": {},
        "type_total_counts": {},
        "dead_docs": [],
        "total_accuracy_errors": 0,
        "live_doc_count": 1,
        "accuracy_errors_per_doc": 0.0,
        "accuracy_by_category": {},
        "junk_total_lines": 0,
        "junk_total_source_lines": 100,
        "junk_fraction": 0.0,
        "junk_item_count": 0,
        "junk_file_count": 0,
        "junk_by_category": {},
        "junk_by_category_lines": {},
        "junk_entries": [],
        "junk_sources": [],
        "enforcement_total_obligations": None,
        "enforcement_unactuated": None,
        "enforcement_pct_unactuated": None,
        "enforcement_by_schema": None,
        "obligation_violations": None,
        "obligation_implicit_contracts": None,
    }
    _write_audit_result(
        temp_dir,
        [
            {
                "path": "src/mod.py",
                "severity": "warning",
                "category": "dead_code",
                "message": "Unused helper",
                "remediation": "Remove it",
                "line_start": 1,
                "line_end": 1,
            }
        ],
        scorecard=scorecard,
    )

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)
    schema = _load_schema()
    jsonschema.validate(instance=bundle, schema=schema)


def test_audit_finding_with_origin_passes_through(temp_dir):
    _write_source(temp_dir, "main.py", "x = 1\n")
    _write_audit_result(temp_dir, [
        {
            "path": "main.py",
            "severity": "warning",
            "category": "dead_code",
            "message": "Unused var",
            "remediation": "Remove it",
            "line_start": 1,
            "line_end": 1,
            "origin": {"source": "static", "plugin": "eslint"},
        }
    ])

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)
    file_node = _find_file_node(bundle["tree"], "main.py")
    assert len(file_node["audit_findings"]) == 1
    finding = file_node["audit_findings"][0]
    assert finding["origin"] == {"source": "static", "plugin": "eslint"}

    schema = _load_schema()
    jsonschema.validate(instance=bundle, schema=schema)


def test_invalid_bundle_fails_schema_validation():
    schema = _load_schema()
    invalid_bundle = {
        "schema_name": "osoji-observatory",
        "schema_version": "1.1.0",
        "osoji_version": "0.2.0",
        "generated_at": "2026-03-13T00:00:00+00:00",
        "audit_status": 123,
        "project": {"name": "test"},
        "metrics": {
            "aggregate_health": None,
            "file_count": 0,
            "dir_count": 1,
            "compression_ratio": None,
            "compression_savings_ratio": None,
        },
        "tokens": {"source_tokens": 0, "shadow_tokens": 0},
        "scorecard": None,
        "import_graph": [],
        "doc_analysis": {},
        "tree": {
            "node_type": "directory",
            "name": "test",
            "path": "",
            "shadow": {"exists": False, "content": None},
            "children": [],
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_bundle, schema=schema)


def test_enriched_bundle_validates_with_all_fields(temp_dir):
    """Comprehensive test exercising junk detail fields, doc analysis findings, and origin fields."""
    content = "def run():\n    return 1\ndef old():\n    pass\n"
    _write_source(temp_dir, "src/app.py", content)
    _write_shadow(
        temp_dir,
        "src/app.py",
        source_hash=compute_hash(content),
        impl_hash=compute_impl_hash(),
    )
    _write_findings(
        temp_dir,
        "src/app.py",
        [
            {
                "category": "dead_code",
                "severity": "warning",
                "line_start": 3,
                "line_end": 4,
                "description": "Unused function old()",
            }
        ],
    )
    _write_symbols(
        temp_dir,
        "src/app.py",
        [
            {"name": "run", "kind": "function", "line_start": 1, "line_end": 2, "visibility": "public"},
            {"name": "old", "kind": "function", "line_start": 3, "line_end": 4, "visibility": "public"},
        ],
    )
    _write_signature(temp_dir, "src/app.py", "Application entry point", ["app", "main"])

    # Doc analysis with real structure (tests A1 fix)
    _write_doc_analysis(temp_dir, "README.md", {
        "classification": "reference",
        "confidence": 0.82,
        "matched_shadows": ["src/app.py"],
        "findings": [
            {
                "category": "stale_content",
                "severity": "warning",
                "description": "References outdated API",
                "evidence": "mentions v1 endpoint",
                "shadow_ref": "src/app.py",
                "remediation": "Update API references",
            },
            {
                "category": "missing_content",
                "severity": "error",
                "description": "Missing setup instructions",
                "evidence": None,
                "shadow_ref": None,
                "remediation": "Add setup section",
            },
        ],
        "topic_signature": {"purpose": "Project overview", "topics": ["CLI", "setup", "API"]},
    })

    # Scorecard with enriched junk items (tests B1)
    scorecard = {
        "coverage_entries": [],
        "coverage_pct": 100.0,
        "covered_count": 1,
        "total_source_count": 1,
        "coverage_by_type": {},
        "type_covered_counts": {},
        "type_total_counts": {},
        "dead_docs": [],
        "total_accuracy_errors": 0,
        "live_doc_count": 1,
        "accuracy_errors_per_doc": 0.0,
        "accuracy_by_category": {},
        "junk_total_lines": 2,
        "junk_total_source_lines": 4,
        "junk_fraction": 0.5,
        "junk_item_count": 1,
        "junk_file_count": 1,
        "junk_by_category": {"dead_symbol": 1},
        "junk_by_category_lines": {"dead_symbol": 2},
        "junk_entries": [
            {
                "source_path": "src/app.py",
                "total_lines": 4,
                "junk_lines": 2,
                "junk_fraction": 0.5,
                "items": [
                    {
                        "category": "dead_symbol",
                        "line_start": 3,
                        "line_end": 4,
                        "source": "dead_code",
                        "confidence_source": "llm_inferred",
                        "name": "old",
                        "kind": "function",
                        "reason": "Never called anywhere",
                        "remediation": "Remove the function",
                        "confidence": 0.85,
                    }
                ],
            }
        ],
        "junk_sources": ["dead_code"],
        "enforcement_total_obligations": None,
        "enforcement_unactuated": None,
        "enforcement_pct_unactuated": None,
        "enforcement_by_schema": None,
        "obligation_violations": None,
        "obligation_implicit_contracts": None,
    }

    # Audit findings with origin (tests B3)
    _write_audit_result(
        temp_dir,
        [
            {
                "path": "src/app.py",
                "severity": "warning",
                "category": "dead_code",
                "message": "Unused function old()",
                "remediation": "Remove it",
                "line_start": 3,
                "line_end": 4,
                "origin": {"source": "llm", "plugin": "code_debris"},
            },
            {
                "path": "src/app.py",
                "severity": "warning",
                "category": "stale_shadow",
                "message": "Shadow documentation is stale",
                "remediation": "Run 'osoji shadow .' to update",
                "line_start": None,
                "line_end": None,
                "origin": {"source": "static", "plugin": "shadow_check"},
            },
        ],
        scorecard=scorecard,
    )

    bundle = build_observatory_bundle(temp_dir, respect_gitignore=False)

    # Validate against JSON Schema
    schema = _load_schema()
    jsonschema.validate(instance=bundle, schema=schema)

    # A1: doc_analysis has non-null purpose and topics from topic_signature
    analysis = bundle["doc_analysis"]["README.md"]
    assert analysis["purpose"] == "Project overview"
    assert analysis["topics"] == ["CLI", "setup", "API"]
    assert analysis["matched_sources"] == ["src/app.py"]
    assert analysis["accuracy_error_count"] == 2  # len(findings)

    # B2: doc_analysis entries have findings array
    assert len(analysis["findings"]) == 2
    assert analysis["findings"][0]["description"] == "References outdated API"
    assert analysis["findings"][0]["evidence"] == "mentions v1 endpoint"
    assert analysis["findings"][1]["severity"] == "error"
    assert analysis["findings"][1]["remediation"] == "Add setup section"

    # B1: junk items have enriched fields
    junk_entries = bundle["scorecard"]["junk_entries"]
    assert len(junk_entries) == 1
    junk_item = junk_entries[0]["items"][0]
    assert junk_item["name"] == "old"
    assert junk_item["kind"] == "function"
    assert junk_item["reason"] == "Never called anywhere"
    assert junk_item["remediation"] == "Remove the function"
    assert junk_item["confidence"] == 0.85

    # B3: audit findings have origin
    file_node = _find_file_node(bundle["tree"], "src", "app.py")
    origins = [f.get("origin") for f in file_node["audit_findings"] if f.get("origin")]
    assert len(origins) >= 1
    assert any(o["source"] == "llm" and o["plugin"] == "code_debris" for o in origins)
    assert any(o["source"] == "static" and o["plugin"] == "shadow_check" for o in origins)
