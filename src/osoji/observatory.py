"""Stable observatory export bundle for downstream consumers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .hasher import (
    compute_file_hash,
    compute_impl_hash,
    extract_impl_hash,
    extract_source_hash,
    is_findings_current,
)
from .facts import FactsDB
from .scorecard import merge_ranges
from .walker import discover_directories, discover_files

OBSERVATORY_SCHEMA_NAME = "osoji-observatory"
OBSERVATORY_SCHEMA_VERSION = "1.1.0"
_DEFAULT_OUTPUT_NAME = "observatory.json"
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _count_lines(path: Path) -> int:
    """Count lines in a file. Returns 0 on error."""
    try:
        return len(path.read_text(errors="ignore").splitlines())
    except OSError:
        return 0


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    """Read and parse a JSON file, returning None on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _normalize_path(value: Path | str) -> str:
    """Normalize a project-relative path to forward slashes."""
    text = str(value)
    if text in ("", "."):
        return ""
    return text.replace("\\", "/")


def _compute_file_health(metrics: dict[str, Any], shadow_exists: bool, is_stale: bool) -> float | None:
    """Compute a single file health score in the range 0.0-1.0."""
    error_count = int(metrics.get("error_count", 0) or 0)
    warning_count = int(metrics.get("warning_count", 0) or 0)
    junk_fraction = float(metrics.get("junk_fraction", 0.0) or 0.0)

    if not shadow_exists and error_count == 0 and warning_count == 0:
        return None

    penalty = 0.8
    score = 1.0

    if not shadow_exists:
        score *= penalty

    if is_stale:
        score *= penalty

    for _ in range(error_count):
        score *= penalty
    for _ in range(warning_count):
        score *= penalty

    if junk_fraction > 0:
        score *= max(0.0, 0.8 - junk_fraction)

    return max(0.0, min(1.0, score))


def _compute_aggregate_health(file_nodes: list[dict[str, Any]]) -> float | None:
    """Weighted average of file health scores by line count."""
    total_weight = 0
    weighted_sum = 0.0

    for node in file_nodes:
        health = node["metrics"]["health_score"]
        if health is None:
            continue
        lines = int(node.get("lines", 0) or 0)
        total_weight += lines
        weighted_sum += lines * health

    if total_weight == 0:
        return None
    return weighted_sum / total_weight


def _sort_audit_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return findings sorted for stable downstream rendering."""

    def _key(item: dict[str, Any]) -> tuple[int, int, int, str, str]:
        severity = str(item.get("severity", "warning"))
        line_start = item.get("line_start")
        line_end = item.get("line_end")
        start = line_start if isinstance(line_start, int) else 10**9
        end = line_end if isinstance(line_end, int) else start
        return (
            _SEVERITY_ORDER.get(severity, len(_SEVERITY_ORDER)),
            start,
            end,
            str(item.get("category", "")),
            str(item.get("message", "")),
        )

    return sorted(findings, key=_key)


def _load_audit_findings_by_path(config: Config) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    """Load normalized audit findings keyed by project-relative file path."""
    audit_result = _safe_read_json(config.analysis_root / "audit-result.json")
    if audit_result is None:
        return "missing", {}

    by_path: dict[str, list[dict[str, Any]]] = {}
    for issue in audit_result.get("issues", []):
        if not isinstance(issue, dict):
            continue
        rel_path = _normalize_path(issue.get("path", ""))
        if not rel_path:
            continue
        finding = {
            "severity": issue.get("severity", "warning"),
            "category": issue.get("category", "unknown"),
            "message": issue.get("message", ""),
            "remediation": issue.get("remediation"),
            "line_start": issue.get("line_start"),
            "line_end": issue.get("line_end"),
        }
        if "origin" in issue:
            finding["origin"] = issue["origin"]
        by_path.setdefault(rel_path, []).append(finding)

    for rel_path, findings in by_path.items():
        by_path[rel_path] = _sort_audit_findings(findings)

    return "present", by_path


def _build_import_graph_edges(facts_db: FactsDB) -> list[dict[str, Any]]:
    """Build an edge list of file-to-file import relationships."""
    # Aggregate by (source, target) pair
    edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for file_path in facts_db.all_files():
        file_facts = facts_db.get_file(file_path)
        if file_facts is None or file_facts.classification is not None:
            continue  # skip doc files
        for imp in file_facts.imports:
            resolved = facts_db.resolve_import_source(file_path, imp.get("source", ""))
            if resolved is None:
                continue
            key = (file_path, resolved)
            if key not in edge_map:
                edge_map[key] = {
                    "source": file_path,
                    "target": resolved,
                    "names": [],
                    "is_reexport": False,
                }
            names = imp.get("names", [])
            edge_map[key]["names"].extend(n for n in names if n not in edge_map[key]["names"])
            if imp.get("is_reexport", False):
                edge_map[key]["is_reexport"] = True
    return list(edge_map.values())


def _build_doc_analysis(config: Config) -> dict[str, dict[str, Any]]:
    """Load doc analysis summaries from analysis/docs/*.analysis.json."""
    docs_dir = config.analysis_root / "docs"
    if not docs_dir.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for analysis_file in sorted(docs_dir.rglob("*.analysis.json")):
        data = _safe_read_json(analysis_file)
        if not data:
            continue
        rel = str(analysis_file.relative_to(docs_dir))
        suffix = ".analysis.json"
        if not rel.endswith(suffix):
            continue
        doc_path = rel[: -len(suffix)].replace("\\", "/")
        result[doc_path] = {
            "classification": data.get("classification"),
            "confidence": data.get("confidence"),
            "purpose": data.get("purpose"),
            "topics": data.get("topics", []),
            "matched_sources": data.get("matched_sources", []),
            "accuracy_error_count": data.get("accuracy_error_count", 0),
        }
    return result


def _build_facts_summary(
    rel_path: str, facts_db: FactsDB | None,
) -> dict[str, Any] | None:
    """Build a facts summary for a single file node."""
    if facts_db is None:
        return None
    file_facts = facts_db.get_file(rel_path)
    if file_facts is None:
        return None
    resolved_imports = []
    for imp in file_facts.imports:
        resolved_target = facts_db.resolve_import_source(rel_path, imp.get("source", ""))
        resolved_imports.append({
            "resolved_target": resolved_target,
            "names": imp.get("names", []),
        })
    return {
        "imports": resolved_imports,
        "exports": [
            {"name": e.get("name", ""), "kind": e.get("kind", ""), "line": e.get("line")}
            for e in file_facts.exports
        ],
        "calls": [
            {"from_symbol": c.get("from_symbol", ""), "to": c.get("to", ""), "line": c.get("line")}
            for c in file_facts.calls
        ],
    }


def _build_file_node(
    config: Config,
    file_path: Path,
    token_cache: dict[str, dict[str, Any]],
    audit_findings_by_path: dict[str, list[dict[str, Any]]],
    facts_db: FactsDB | None = None,
) -> dict[str, Any]:
    """Build a stable observatory node for a single file."""
    rel_path = _normalize_path(file_path.relative_to(config.root_path))
    lines = _count_lines(file_path)

    shadow_exists = False
    is_stale = False
    shadow_content: str | None = None

    shadow_path = config.shadow_path_for(file_path)
    if shadow_path.exists():
        try:
            shadow_content = shadow_path.read_text(encoding="utf-8")
            shadow_exists = True
            stored_hash = extract_source_hash(shadow_content)
            if stored_hash is not None:
                try:
                    current_hash = compute_file_hash(file_path)
                    if stored_hash != current_hash:
                        is_stale = True
                    else:
                        cached_impl = extract_impl_hash(shadow_content)
                        if cached_impl is None or cached_impl != compute_impl_hash():
                            is_stale = True
                except OSError:
                    pass
        except OSError:
            pass

    raw_findings = []
    error_count = 0
    warning_count = 0
    junk_fraction = 0.0
    findings_data = _safe_read_json(config.findings_path_for(file_path))
    if findings_data and is_findings_current(
        findings_data.get("source_hash"), findings_data.get("impl_hash"),
        file_path,
    ):
        findings_value = findings_data.get("findings", [])
        if isinstance(findings_value, list):
            raw_findings = findings_value

    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        severity = finding.get("severity", "warning")
        if severity == "error":
            error_count += 1
        else:
            warning_count += 1

    if raw_findings and lines > 0:
        ranges = []
        for finding in raw_findings:
            if not isinstance(finding, dict):
                continue
            line_start = finding.get("line_start", 0)
            line_end = finding.get("line_end", line_start)
            if isinstance(line_start, int) and isinstance(line_end, int) and line_start > 0 and line_end >= line_start:
                ranges.append((line_start, line_end))
        if ranges:
            merged = merge_ranges(ranges)
            junk_lines = sum(end - start + 1 for start, end in merged)
            junk_fraction = min(junk_lines / lines, 1.0)

    symbols_list = []
    file_role = None
    symbols_data = _safe_read_json(config.symbols_path_for(file_path))
    if symbols_data:
        symbols_value = symbols_data.get("symbols", [])
        if isinstance(symbols_value, list):
            symbols_list = [item for item in symbols_value if isinstance(item, dict)]
        file_role = symbols_data.get("file_role")

    public_symbol_count = sum(
        1 for symbol in symbols_list if symbol.get("visibility") == "public"
    )

    signature_data = _safe_read_json(config.signatures_path_for(file_path))
    signature = {
        "purpose": None,
        "topics": [],
        "public_surface": [],
    }
    if signature_data:
        topics = signature_data.get("topics", [])
        public_surface = signature_data.get("public_surface", [])
        signature = {
            "purpose": signature_data.get("purpose"),
            "topics": topics if isinstance(topics, list) else [],
            "public_surface": public_surface if isinstance(public_surface, list) else [],
        }

    token_data = token_cache.get(rel_path, {})
    tokens = {
        "source_tokens": token_data.get("source_tokens"),
        "shadow_tokens": token_data.get("shadow_tokens"),
    }

    audit_findings = list(audit_findings_by_path.get(rel_path, []))
    metrics = {
        "health_score": None,
        "junk_fraction": junk_fraction,
        "error_count": error_count,
        "warning_count": warning_count,
        "findings_count": len(raw_findings),
        "audit_findings_count": len(audit_findings),
    }
    metrics["health_score"] = _compute_file_health(metrics, shadow_exists, is_stale)

    facts_summary = _build_facts_summary(rel_path, facts_db)

    return {
        "node_type": "file",
        "name": file_path.name,
        "path": rel_path,
        "lines": lines,
        "shadow": {
            "exists": shadow_exists,
            "is_stale": is_stale,
            "content": shadow_content,
        },
        "signature": signature,
        "symbols": {
            "count": len(symbols_list),
            "public_count": public_symbol_count,
            "file_role": file_role,
        },
        "tokens": tokens,
        "metrics": metrics,
        "audit_findings": audit_findings,
        "facts_summary": facts_summary,
    }


def _build_directory_nodes(config: Config, dirs: list[Path]) -> dict[str, dict[str, Any]]:
    """Build stable observatory directory nodes keyed by normalized path."""
    dir_nodes: dict[str, dict[str, Any]] = {}

    for dir_path in dirs:
        rel_path = _normalize_path(dir_path.relative_to(config.root_path))
        name = dir_path.name or config.root_path.name
        shadow_path = config.shadow_path_for_dir(dir_path)
        shadow_content: str | None = None
        if shadow_path.exists():
            try:
                shadow_content = shadow_path.read_text(encoding="utf-8")
            except OSError:
                pass

        dir_nodes[rel_path] = {
            "node_type": "directory",
            "name": name,
            "path": rel_path,
            "shadow": {
                "exists": shadow_content is not None,
                "content": shadow_content,
            },
            "children": [],
        }

    return dir_nodes


def _link_tree(
    root_path: Path,
    dir_nodes: dict[str, dict[str, Any]],
    file_nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach directory and file nodes into a nested tree."""
    for rel_path, node in file_nodes.items():
        parent_path = _normalize_path(Path(rel_path).parent)
        dir_nodes[parent_path]["children"].append(node)

    for rel_path, node in dir_nodes.items():
        if rel_path == "":
            continue
        parent_path = _normalize_path(Path(rel_path).parent)
        dir_nodes[parent_path]["children"].append(node)

    for node in dir_nodes.values():
        node["children"].sort(
            key=lambda child: (0 if child["node_type"] == "directory" else 1, child["name"])
        )

    return dir_nodes.get(
        "",
        {
            "node_type": "directory",
            "name": root_path.name,
            "path": "",
            "shadow": {"exists": False, "content": None},
            "children": [],
        },
    )


def _build_bundle_for_config(config: Config) -> dict[str, Any]:
    files = discover_files(config)
    dirs = discover_directories(config, files)

    token_cache = _safe_read_json(config.token_cache_path) or {}
    audit_status, audit_findings_by_path = _load_audit_findings_by_path(config)

    # Instantiate FactsDB once for import graph and per-file facts_summary
    facts_dir = config.root_path / ".osoji" / "facts"
    facts_db: FactsDB | None = None
    if facts_dir.exists():
        facts_db = FactsDB(config)

    file_nodes: dict[str, dict[str, Any]] = {}
    for file_path in files:
        node = _build_file_node(config, file_path, token_cache, audit_findings_by_path, facts_db)
        file_nodes[node["path"]] = node

    dir_nodes = _build_directory_nodes(config, dirs)
    tree = _link_tree(config.root_path, dir_nodes, file_nodes)

    file_node_list = list(file_nodes.values())
    aggregate_health = _compute_aggregate_health(file_node_list)

    total_source_tokens = 0
    total_shadow_tokens = 0
    for node in file_node_list:
        source_tokens = node["tokens"].get("source_tokens")
        shadow_tokens = node["tokens"].get("shadow_tokens")
        if isinstance(source_tokens, int):
            total_source_tokens += source_tokens
        if isinstance(shadow_tokens, int):
            total_shadow_tokens += shadow_tokens

    compression_ratio = None
    compression_savings_ratio = None
    if total_source_tokens > 0:
        compression_ratio = total_shadow_tokens / total_source_tokens
        compression_savings_ratio = 1.0 - compression_ratio

    scorecard = _safe_read_json(config.scorecard_path)
    if scorecard is None:
        audit_result = _safe_read_json(config.analysis_root / "audit-result.json")
        if audit_result and isinstance(audit_result.get("scorecard"), dict):
            scorecard = audit_result["scorecard"]

    # Build import graph edges
    import_graph = _build_import_graph_edges(facts_db) if facts_db else []

    # Build doc analysis summaries
    doc_analysis = _build_doc_analysis(config)

    # Load doc_prompts and config from audit result if present
    doc_prompts_data = None
    config_snapshot = None
    audit_result = _safe_read_json(config.analysis_root / "audit-result.json")
    if audit_result:
        if isinstance(audit_result.get("doc_prompts"), dict):
            doc_prompts_data = audit_result["doc_prompts"]
        if isinstance(audit_result.get("config"), dict):
            config_snapshot = audit_result["config"]

    return {
        "schema_name": OBSERVATORY_SCHEMA_NAME,
        "schema_version": OBSERVATORY_SCHEMA_VERSION,
        "osoji_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audit_status": audit_status,
        "project": {
            "name": config.root_path.name,
        },
        "metrics": {
            "aggregate_health": round(aggregate_health, 4) if aggregate_health is not None else None,
            "file_count": len(file_node_list),
            "dir_count": len(dir_nodes),
            "compression_ratio": round(compression_ratio, 4) if compression_ratio is not None else None,
            "compression_savings_ratio": (
                round(compression_savings_ratio, 4)
                if compression_savings_ratio is not None
                else None
            ),
        },
        "tokens": {
            "source_tokens": total_source_tokens,
            "shadow_tokens": total_shadow_tokens,
        },
        "scorecard": scorecard,
        "import_graph": import_graph,
        "doc_analysis": doc_analysis,
        "doc_prompts": doc_prompts_data,
        "config": config_snapshot,
        "tree": tree,
    }


def build_observatory_bundle(root_path: Path, *, respect_gitignore: bool = True) -> dict[str, Any]:
    """Build the stable observatory export bundle for a project."""
    config = Config(root_path=root_path.resolve(), respect_gitignore=respect_gitignore)
    return _build_bundle_for_config(config)


def write_observatory_bundle(
    root_path: Path,
    *,
    output_path: Path | None = None,
    respect_gitignore: bool = True,
) -> Path:
    """Write the observatory bundle to disk and return the output path."""
    config = Config(root_path=root_path.resolve(), respect_gitignore=respect_gitignore)
    bundle = _build_bundle_for_config(config)
    destination = output_path or (config.analysis_root / _DEFAULT_OUTPUT_NAME)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return destination


__all__ = [
    "OBSERVATORY_SCHEMA_NAME",
    "OBSERVATORY_SCHEMA_VERSION",
    "build_observatory_bundle",
    "write_observatory_bundle",
]
