"""Scorecard: pure-Python aggregation of audit phase results into headline metrics."""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Config, DIRECTORY_SHADOW_FILENAME, SHADOW_DIR
from .doc_analysis import DocAnalysisResult
from .hasher import is_findings_current
from .junk import JunkAnalysisResult


@dataclass
class CoverageEntry:
    source_path: str
    topic_signature: dict | None
    covering_docs: list[dict]  # [{"path": str, "classification": str}]


@dataclass
class JunkCodeEntry:
    source_path: str
    total_lines: int
    junk_lines: int
    junk_fraction: float
    items: list[dict]


@dataclass
class Scorecard:
    # Coverage
    coverage_entries: list[CoverageEntry]
    coverage_pct: float
    covered_count: int
    total_source_count: int
    coverage_by_type: dict[str, float]
    type_covered_counts: dict[str, int]
    type_total_counts: dict[str, int]

    # Dead docs
    dead_docs: list[str]

    # Accuracy
    total_accuracy_errors: int
    live_doc_count: int
    accuracy_errors_per_doc: float
    accuracy_by_category: dict[str, int]

    # Junk code
    junk_total_lines: int
    junk_total_source_lines: int
    junk_fraction: float
    junk_item_count: int
    junk_file_count: int
    junk_by_category: dict[str, int]
    junk_by_category_lines: dict[str, int]
    junk_entries: list[JunkCodeEntry]
    junk_sources: list[str]  # which phases contributed

    # Enforcement (None if --dead-plumbing not run)
    enforcement_total_obligations: int | None
    enforcement_unactuated: int | None
    enforcement_pct_unactuated: float | None
    enforcement_by_schema: dict[str, dict] | None

    # Obligations (None if --obligations not run)
    obligation_violations: int | None = None
    obligation_implicit_contracts: int | None = None

    # Concept-centric coverage (None if --doc-prompts not run)
    concept_total: int | None = None
    concept_fully_documented: int | None = None
    concept_partially_documented: int | None = None
    concept_undocumented: int | None = None
    concept_coverage_by_type: dict[str, dict] | None = None


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping integer ranges. Returns sorted, non-overlapping ranges."""
    if not ranges:
        return []
    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def count_lines(path: Path) -> int:
    """Count lines in a file. Returns 0 on error."""
    try:
        return len(path.read_text(errors="ignore").splitlines())
    except OSError:
        return 0


def _load_signature(config: Config, source_path: str) -> dict | None:
    """Load a topic signature for a source file, if available."""
    sig_path = config.signatures_path_for(Path(source_path))
    if sig_path.exists():
        try:
            return json.loads(sig_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def build_scorecard(
    config: Config,
    analysis_results: list[DocAnalysisResult],
    junk_results: dict[str, JunkAnalysisResult] | None = None,
) -> Scorecard:
    """Build a scorecard from audit phase outputs. Pure Python, no LLM calls."""

    # --- Coverage ---
    # Enumerate all source files from shadow inventory
    shadow_root = config.shadow_root
    all_source_files: set[str] = set()
    if shadow_root.exists():
        for shadow_file in shadow_root.rglob("*.shadow.md"):
            if shadow_file.name == DIRECTORY_SHADOW_FILENAME:
                continue
            relative = shadow_file.relative_to(shadow_root)
            source_str = str(relative).removesuffix(".shadow.md").replace("\\", "/")
            if config.is_doc_candidate(Path(source_str)):
                continue
            all_source_files.add(source_str)

    # Invert matched_shadows: source -> list of covering docs
    source_to_docs: dict[str, list[dict]] = {s: [] for s in all_source_files}
    for item in analysis_results:
        if item.is_debris:
            continue
        for shadow_path in item.matched_shadows:
            normalized = shadow_path.replace("\\", "/")
            if normalized in source_to_docs:
                source_to_docs[normalized].append({
                    "path": str(item.path),
                    "classification": item.classification,
                })

    coverage_entries: list[CoverageEntry] = []
    for source_path in sorted(all_source_files):
        sig = _load_signature(config, source_path)
        covering = source_to_docs.get(source_path, [])
        coverage_entries.append(CoverageEntry(
            source_path=source_path,
            topic_signature=sig,
            covering_docs=covering,
        ))

    covered_count = sum(1 for e in coverage_entries if e.covering_docs)
    total_sources = len(coverage_entries)
    coverage_pct = (covered_count / total_sources * 100) if total_sources > 0 else 0.0

    # Coverage by Diataxis type
    type_covered: dict[str, int] = {}
    type_total: dict[str, int] = {}
    for item in analysis_results:
        if item.is_debris:
            continue
        cls = item.classification
        type_total[cls] = type_total.get(cls, 0) + 1
        if item.matched_shadows:
            type_covered[cls] = type_covered.get(cls, 0) + 1
    coverage_by_type: dict[str, float] = {}
    for cls in type_total:
        total = type_total[cls]
        covered = type_covered.get(cls, 0)
        coverage_by_type[cls] = (covered / total * 100) if total > 0 else 0.0

    # --- Dead docs ---
    dead_docs = [str(item.path).replace("\\", "/") for item in analysis_results if item.is_debris]

    # --- Accuracy ---
    live_results = [item for item in analysis_results if not item.is_debris]
    live_doc_count = len(live_results)
    accuracy_by_category: dict[str, int] = {}
    total_accuracy_errors = 0
    for item in live_results:
        for finding in item.findings:
            if finding.severity == "error":
                total_accuracy_errors += 1
                cat = finding.category
                accuracy_by_category[cat] = accuracy_by_category.get(cat, 0) + 1
    accuracy_errors_per_doc = (total_accuracy_errors / live_doc_count) if live_doc_count > 0 else 0.0

    # --- Junk code ---
    # Collect junk items from all sources, keyed by source_path
    junk_items_by_file: dict[str, list[dict]] = {}
    junk_sources: list[str] = []

    # Code debris findings from .osoji/findings/
    findings_dir = config.root_path / SHADOW_DIR / "findings"
    if findings_dir.exists():
        junk_sources.append("code_debris")
        for findings_file in findings_dir.rglob("*.findings.json"):
            try:
                data = json.loads(findings_file.read_text(encoding="utf-8"))
                source = data.get("source", "")
                if not is_findings_current(
                    data.get("source_hash"), data.get("impl_hash"),
                    config.root_path / source,
                ):
                    continue
                for f in data.get("findings", []):
                    if source not in junk_items_by_file:
                        junk_items_by_file[source] = []
                    junk_items_by_file[source].append({
                        "category": f["category"],
                        "line_start": f["line_start"],
                        "line_end": f["line_end"],
                        "source": "code_debris",
                    })
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    # Unified junk results (new path)
    if junk_results:
        for analyzer_name, result in junk_results.items():
            junk_sources.append(analyzer_name)
            for item in result.findings:
                source = item.source_path.replace("\\", "/")
                junk_items_by_file.setdefault(source, []).append({
                    "category": item.category,
                    "line_start": item.line_start,
                    "line_end": item.line_end or item.line_start,
                    "source": analyzer_name,
                    "confidence_source": item.confidence_source,
                    "name": item.name,
                    "kind": item.kind,
                    "reason": item.reason,
                    "remediation": item.remediation,
                    "confidence": item.confidence,
                })

    # Compute junk lines per file with merged ranges
    junk_entries: list[JunkCodeEntry] = []
    junk_total_lines = 0
    junk_item_count = 0
    junk_by_category: dict[str, int] = {}
    junk_by_category_lines: dict[str, int] = {}

    # We need total source lines across ALL source files for the denominator
    junk_total_source_lines = 0
    for source_path in all_source_files:
        full_path = config.root_path / source_path
        lines = count_lines(full_path)
        junk_total_source_lines += lines

    for source, items in junk_items_by_file.items():
        full_path = config.root_path / source
        file_lines = count_lines(full_path)

        # Merge overlapping ranges
        ranges = [(it["line_start"], it["line_end"]) for it in items]
        merged = merge_ranges(ranges)
        file_junk_lines = sum(end - start + 1 for start, end in merged)

        junk_total_lines += file_junk_lines
        junk_item_count += len(items)

        for it in items:
            cat = it["category"]
            junk_by_category[cat] = junk_by_category.get(cat, 0) + 1
            item_lines = it["line_end"] - it["line_start"] + 1
            junk_by_category_lines[cat] = junk_by_category_lines.get(cat, 0) + item_lines

        fraction = (file_junk_lines / file_lines) if file_lines > 0 else 0.0
        junk_entries.append(JunkCodeEntry(
            source_path=source,
            total_lines=file_lines,
            junk_lines=file_junk_lines,
            junk_fraction=fraction,
            items=items,
        ))

    junk_entries.sort(key=lambda e: e.junk_fraction, reverse=True)
    junk_fraction = (junk_total_lines / junk_total_source_lines) if junk_total_source_lines > 0 else 0.0
    junk_file_count = len(junk_items_by_file)

    # --- Enforcement ---
    _plumbing_junk = junk_results.get("dead_plumbing") if junk_results else None

    if _plumbing_junk is not None:
        enforcement_total = _plumbing_junk.total_candidates
        enforcement_unactuated = len(_plumbing_junk.findings)
        enforcement_pct = (enforcement_unactuated / enforcement_total * 100) if enforcement_total > 0 else 0.0

        enforcement_by_schema: dict[str, dict] = {}
        for f in _plumbing_junk.findings:
            schema_name = f.metadata.get("schema_name", "")
            key = f"{f.source_path}:{schema_name}" if schema_name else f.source_path
            if key not in enforcement_by_schema:
                enforcement_by_schema[key] = {"unactuated": 0, "fields": []}
            enforcement_by_schema[key]["unactuated"] += 1
            enforcement_by_schema[key]["fields"].append(f.name)
    else:
        enforcement_total = None
        enforcement_unactuated = None
        enforcement_pct = None
        enforcement_by_schema = None

    return Scorecard(
        coverage_entries=coverage_entries,
        coverage_pct=coverage_pct,
        covered_count=covered_count,
        total_source_count=total_sources,
        coverage_by_type=coverage_by_type,
        type_covered_counts=type_covered,
        type_total_counts=type_total,
        dead_docs=dead_docs,
        total_accuracy_errors=total_accuracy_errors,
        live_doc_count=live_doc_count,
        accuracy_errors_per_doc=accuracy_errors_per_doc,
        accuracy_by_category=accuracy_by_category,
        junk_total_lines=junk_total_lines,
        junk_total_source_lines=junk_total_source_lines,
        junk_fraction=junk_fraction,
        junk_item_count=junk_item_count,
        junk_file_count=junk_file_count,
        junk_by_category=junk_by_category,
        junk_by_category_lines=junk_by_category_lines,
        junk_entries=junk_entries,
        junk_sources=junk_sources,
        enforcement_total_obligations=enforcement_total,
        enforcement_unactuated=enforcement_unactuated,
        enforcement_pct_unactuated=enforcement_pct,
        enforcement_by_schema=enforcement_by_schema,
    )
