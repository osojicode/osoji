"""Tests for the observatory export bundle."""

import json
from pathlib import Path

from click.testing import CliRunner

from osoji.cli import main
from osoji.hasher import compute_hash, compute_impl_hash
from osoji.observatory import (
    OBSERVATORY_SCHEMA_NAME,
    OBSERVATORY_SCHEMA_VERSION,
    build_observatory_bundle,
)


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
    from osoji.hasher import compute_file_hash, compute_impl_hash
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
