"""Scorecard phase: aggregated documentation health metrics."""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config


@dataclass
class CoverageEntry:
    """One row of the coverage matrix."""

    source_path: str
    topic_signature: dict | None  # None if signature not yet generated
    covering_docs: list[dict] = field(default_factory=list)  # [{"path": str, "classification": str}]


@dataclass
class Scorecard:
    """Aggregated documentation health metrics."""

    # Coverage
    coverage_entries: list[CoverageEntry] = field(default_factory=list)
    coverage_pct: float = 0.0  # % of source modules with >= 1 covering doc
    coverage_by_type: dict[str, float] = field(default_factory=dict)  # {diataxis_type: %}

    # Dead docs
    dead_docs: list[str] = field(default_factory=list)

    # Accuracy (errors per doc)
    total_accuracy_errors: int = 0
    live_doc_count: int = 0
    accuracy_errors_per_doc: float = 0.0
    accuracy_by_category: dict[str, int] = field(default_factory=dict)

    # Hygiene (warnings per source file)
    total_hygiene_warnings: int = 0
    source_file_count: int = 0
    hygiene_warnings_per_file: float = 0.0
    hygiene_by_category: dict[str, int] = field(default_factory=dict)


def _load_signature(config: Config, source_path: str) -> dict | None:
    """Load a topic signature from .docstar/signatures/ if it exists."""
    sig_path = config.root_path / ".docstar" / "signatures" / (source_path + ".signature.json")
    if not sig_path.exists():
        return None
    try:
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        return {
            "purpose": data.get("purpose", ""),
            "topics": data.get("topics", []),
        }
    except (json.JSONDecodeError, OSError):
        return None


def _shadow_path_to_source(shadow_path: Path, shadow_root: Path) -> str:
    """Convert a shadow doc path back to a relative source path string."""
    relative = shadow_path.relative_to(shadow_root)
    return str(relative).removesuffix(".shadow.md").replace("\\", "/")


def build_scorecard(
    config: Config,
    analysis_results: list | None = None,
    dead_code_results: list | None = None,
) -> Scorecard:
    """Build a scorecard from phase outputs.

    Args:
        config: Docstar configuration.
        analysis_results: Phase 2 DocAnalysisResult objects (in-memory).
        dead_code_results: Phase 4 DeadCodeVerification objects (in-memory), if available.

    Returns:
        Populated Scorecard.
    """
    if analysis_results is None:
        analysis_results = []

    scorecard = Scorecard()

    # --- Dead docs ---
    scorecard.dead_docs = [str(r.path) for r in analysis_results if r.is_debris]

    # --- Coverage ---
    # Build coverage map: source_path -> [covering docs]
    coverage_map: dict[str, list[dict]] = defaultdict(list)
    for doc_result in analysis_results:
        if doc_result.is_debris:
            continue
        for shadow_path in doc_result.matched_shadows:
            coverage_map[shadow_path].append({
                "path": str(doc_result.path),
                "classification": doc_result.classification,
            })

    # Build entries for ALL source files from shadow doc inventory
    shadow_root = config.shadow_root
    all_source_paths: list[str] = []
    if shadow_root.exists():
        for shadow_file in sorted(shadow_root.rglob("*.shadow.md")):
            if shadow_file.name == "_directory.shadow.md":
                continue
            source_path = _shadow_path_to_source(shadow_file, shadow_root)
            all_source_paths.append(source_path)

    for source_path in all_source_paths:
        sig = _load_signature(config, source_path)
        scorecard.coverage_entries.append(CoverageEntry(
            source_path=source_path,
            topic_signature=sig,
            covering_docs=coverage_map.get(source_path, []),
        ))

    if scorecard.coverage_entries:
        covered = len([e for e in scorecard.coverage_entries if e.covering_docs])
        scorecard.coverage_pct = covered / len(scorecard.coverage_entries)
    else:
        scorecard.coverage_pct = 0.0

    # Coverage by Diataxis type
    diataxis_types = ["reference", "tutorial", "how-to", "explanatory"]
    for dtype in diataxis_types:
        if not scorecard.coverage_entries:
            scorecard.coverage_by_type[dtype] = 0.0
            continue
        covered_by_type = sum(
            1 for e in scorecard.coverage_entries
            if any(d["classification"] == dtype for d in e.covering_docs)
        )
        scorecard.coverage_by_type[dtype] = covered_by_type / len(scorecard.coverage_entries)

    # --- Accuracy ---
    live_results = [r for r in analysis_results if not r.is_debris]
    scorecard.live_doc_count = len(live_results)

    accuracy_errors = []
    for r in live_results:
        for f in r.findings:
            if f.severity == "error":
                accuracy_errors.append(f)

    scorecard.total_accuracy_errors = len(accuracy_errors)
    scorecard.accuracy_errors_per_doc = (
        len(accuracy_errors) / len(live_results) if live_results else 0.0
    )
    scorecard.accuracy_by_category = dict(Counter(f.category for f in accuracy_errors))

    # --- Hygiene ---
    findings_dir = config.root_path / ".docstar" / "findings"
    hygiene_warnings = []
    findings_file_count = 0

    if findings_dir.exists():
        for findings_file in sorted(findings_dir.rglob("*.findings.json")):
            try:
                data = json.loads(findings_file.read_text(encoding="utf-8"))
                findings_file_count += 1
                for f in data.get("findings", []):
                    if f.get("severity") == "warning":
                        hygiene_warnings.append(f)
            except (json.JSONDecodeError, OSError):
                continue

    scorecard.total_hygiene_warnings = len(hygiene_warnings)
    scorecard.source_file_count = findings_file_count
    scorecard.hygiene_warnings_per_file = (
        len(hygiene_warnings) / findings_file_count if findings_file_count > 0 else 0.0
    )
    scorecard.hygiene_by_category = dict(Counter(
        f.get("category", "unknown") for f in hygiene_warnings
    ))

    return scorecard


def serialize_scorecard(scorecard: Scorecard, config: Config) -> None:
    """Write scorecard to .docstar/analysis/scorecard.json."""
    analysis_dir = config.root_path / ".docstar" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "coverage_pct": scorecard.coverage_pct,
        "coverage_by_type": scorecard.coverage_by_type,
        "dead_docs": scorecard.dead_docs,
        "total_accuracy_errors": scorecard.total_accuracy_errors,
        "live_doc_count": scorecard.live_doc_count,
        "accuracy_errors_per_doc": scorecard.accuracy_errors_per_doc,
        "accuracy_by_category": scorecard.accuracy_by_category,
        "total_hygiene_warnings": scorecard.total_hygiene_warnings,
        "source_file_count": scorecard.source_file_count,
        "hygiene_warnings_per_file": scorecard.hygiene_warnings_per_file,
        "hygiene_by_category": scorecard.hygiene_by_category,
        "coverage_entries": [
            {
                "source_path": e.source_path,
                "topic_signature": e.topic_signature,
                "covering_docs": e.covering_docs,
            }
            for e in scorecard.coverage_entries
        ],
    }

    out_path = analysis_dir / "scorecard.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def format_scorecard_markdown(scorecard: Scorecard) -> str:
    """Render scorecard as markdown for the audit report."""
    lines = []
    lines.append("## Documentation Scorecard")
    lines.append("")

    total_modules = len(scorecard.coverage_entries)
    covered_modules = len([e for e in scorecard.coverage_entries if e.covering_docs])

    lines.append("| Metric | Score |")
    lines.append("|--------|-------|")
    lines.append(f"| Coverage | {scorecard.coverage_pct:.0%} ({covered_modules}/{total_modules} modules) |")
    lines.append(f"| Dead docs | {len(scorecard.dead_docs)} |")
    lines.append(
        f"| Accuracy | {scorecard.accuracy_errors_per_doc:.1f} errors/doc "
        f"({scorecard.total_accuracy_errors} errors across {scorecard.live_doc_count} docs) |"
    )
    lines.append(
        f"| Hygiene | {scorecard.hygiene_warnings_per_file:.1f} warnings/file "
        f"({scorecard.total_hygiene_warnings} warnings across {scorecard.source_file_count} files) |"
    )
    lines.append("")

    # Coverage by type
    if scorecard.coverage_by_type:
        lines.append("### Coverage by Type")
        lines.append("| Type | Coverage |")
        lines.append("|------|----------|")
        for dtype, pct in sorted(scorecard.coverage_by_type.items()):
            lines.append(f"| {dtype.title()} | {pct:.0%} |")
        lines.append("")

    # Dead docs
    if scorecard.dead_docs:
        lines.append("### Dead Docs")
        for doc in sorted(scorecard.dead_docs):
            lines.append(f"- {doc}")
        lines.append("")

    # Accuracy breakdown
    if scorecard.accuracy_by_category:
        lines.append("### Accuracy Breakdown")
        for cat, count in sorted(scorecard.accuracy_by_category.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat.replace('_', ' ').title()}: {count}")
        lines.append("")

    # Hygiene breakdown
    if scorecard.hygiene_by_category:
        lines.append("### Hygiene Breakdown")
        for cat, count in sorted(scorecard.hygiene_by_category.items(), key=lambda x: -x[1]):
            lines.append(f"- {cat.replace('_', ' ').title()}: {count}")
        lines.append("")

    return "\n".join(lines)


def scorecard_to_json(scorecard: Scorecard) -> dict:
    """Convert scorecard to a JSON-serializable dict."""
    return {
        "coverage_pct": scorecard.coverage_pct,
        "coverage_by_type": scorecard.coverage_by_type,
        "dead_docs": scorecard.dead_docs,
        "total_accuracy_errors": scorecard.total_accuracy_errors,
        "live_doc_count": scorecard.live_doc_count,
        "accuracy_errors_per_doc": scorecard.accuracy_errors_per_doc,
        "accuracy_by_category": scorecard.accuracy_by_category,
        "total_hygiene_warnings": scorecard.total_hygiene_warnings,
        "source_file_count": scorecard.source_file_count,
        "hygiene_warnings_per_file": scorecard.hygiene_warnings_per_file,
        "hygiene_by_category": scorecard.hygiene_by_category,
        "coverage_entries": [
            {
                "source_path": e.source_path,
                "topic_signature": e.topic_signature,
                "covering_docs": e.covering_docs,
            }
            for e in scorecard.coverage_entries
        ],
    }
