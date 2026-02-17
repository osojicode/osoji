"""Diff-aware impact analysis for documentation."""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .debris import find_doc_candidates
from .hooks import find_git_root
from .shadow import is_stale
from .walker import _matches_ignore


@dataclass
class DiffFileChange:
    """A file changed between base and HEAD."""

    path: Path  # Relative to repo root
    change_type: str  # "modified", "added", "deleted", "renamed"
    is_source: bool
    is_doc: bool


@dataclass
class StaleShadow:
    """A source file whose shadow doc is stale or missing."""

    source_path: Path
    shadow_exists: bool
    status: str  # "stale", "missing", "deleted_source"


@dataclass
class DocReference:
    """A documentation file that references a changed source file."""

    doc_path: Path  # The .md file
    source_path: Path  # The changed source it references
    line_number: int
    line_content: str
    source_deleted: bool  # True if source was deleted (high severity)


@dataclass
class DiffImpactReport:
    """Complete diff impact analysis result."""

    base_ref: str
    changed_source: list[DiffFileChange] = field(default_factory=list)
    changed_docs: list[DiffFileChange] = field(default_factory=list)
    stale_shadows: list[StaleShadow] = field(default_factory=list)
    doc_references: list[DocReference] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.stale_shadows or self.doc_references)


# Map git diff status letters to human-readable types
_STATUS_MAP = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type_changed",
}


def get_diff_files(repo_root: Path, base_ref: str, config: Config) -> list[DiffFileChange]:
    """Get list of changed files between base_ref and HEAD.

    Runs `git diff <base>...HEAD --name-status` and classifies each file.
    """
    try:
        result = subprocess.run(
            ["git", "diff", f"{base_ref}...HEAD", "--name-status"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"git diff failed: {e.stderr.strip() or e.stdout.strip() or str(e)}"
        )

    docstarignore = config.load_docstarignore()

    changes: list[DiffFileChange] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) < 2:
            continue

        status_code = parts[0][0]  # First char (R100 -> R)
        # For renames, use the destination path
        file_path = Path(parts[-1])

        # Skip files matching ignore patterns
        if _matches_ignore(file_path, config.ignore_patterns):
            continue
        if _matches_ignore(file_path, docstarignore):
            continue

        change_type = _STATUS_MAP.get(status_code, "modified")
        is_source = file_path.suffix in config.extensions
        is_doc = config.is_doc_candidate(repo_root / file_path)

        changes.append(DiffFileChange(
            path=file_path,
            change_type=change_type,
            is_source=is_source,
            is_doc=is_doc,
        ))

    return changes


def check_stale_shadows(config: Config, changed_sources: list[DiffFileChange]) -> list[StaleShadow]:
    """Check which changed source files have stale or missing shadow docs."""
    stale: list[StaleShadow] = []

    for change in changed_sources:
        abs_path = config.root_path / change.path

        if change.change_type == "deleted":
            shadow_path = config.shadow_path_for(abs_path)
            stale.append(StaleShadow(
                source_path=change.path,
                shadow_exists=shadow_path.exists(),
                status="deleted_source",
            ))
            continue

        if not abs_path.exists():
            continue

        shadow_path = config.shadow_path_for(abs_path)
        if not shadow_path.exists():
            stale.append(StaleShadow(
                source_path=change.path,
                shadow_exists=False,
                status="missing",
            ))
        elif is_stale(config, abs_path):
            stale.append(StaleShadow(
                source_path=change.path,
                shadow_exists=True,
                status="stale",
            ))

    return stale


def _build_search_patterns(source_path: Path) -> list[str]:
    """Build text search patterns for a source file path.

    Generates patterns like:
    - "src/docstar/config.py" (full relative path)
    - "config.py" (filename)
    - "docstar.config" (Python module-style)
    """
    patterns = []

    # Full relative path (forward slashes)
    patterns.append(str(source_path).replace("\\", "/"))

    # Filename only
    patterns.append(source_path.name)

    # Module-style reference (for Python files)
    if source_path.suffix == ".py":
        # src/docstar/config.py -> docstar.config
        parts = list(source_path.with_suffix("").parts)
        # Strip common prefixes like "src"
        if parts and parts[0] == "src":
            parts = parts[1:]
        if len(parts) > 1:
            # Remove __init__ from module path
            if parts[-1] == "__init__":
                parts = parts[:-1]
            patterns.append(".".join(parts))

    return patterns


def find_doc_references(config: Config, changed_sources: list[DiffFileChange]) -> list[DocReference]:
    """Search .md files for references to changed source files."""
    if not changed_sources:
        return []

    doc_candidates = find_doc_candidates(config)
    if not doc_candidates:
        return []

    # Build search patterns for each changed source
    source_patterns: list[tuple[DiffFileChange, list[str]]] = []
    for change in changed_sources:
        patterns = _build_search_patterns(change.path)
        source_patterns.append((change, patterns))

    references: list[DocReference] = []

    for doc_path in doc_candidates:
        try:
            content = doc_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        relative_doc = doc_path.relative_to(config.root_path)

        for line_num, line in enumerate(content.splitlines(), start=1):
            for change, patterns in source_patterns:
                for pattern in patterns:
                    if pattern in line:
                        references.append(DocReference(
                            doc_path=relative_doc,
                            source_path=change.path,
                            line_number=line_num,
                            line_content=line.strip(),
                            source_deleted=(change.change_type == "deleted"),
                        ))
                        break  # One match per (line, source) pair is enough

    return references


def run_diff(config: Config, base_ref: str) -> DiffImpactReport:
    """Run full diff impact analysis.

    Orchestrates: git diff -> classify -> stale check -> doc reference search.
    """
    repo_root = find_git_root(config.root_path)
    if repo_root is None:
        raise RuntimeError("Not a git repository")

    changes = get_diff_files(repo_root, base_ref, config)

    if not changes:
        return DiffImpactReport(base_ref=base_ref)

    source_changes = [c for c in changes if c.is_source]
    doc_changes = [c for c in changes if c.is_doc]

    stale = check_stale_shadows(config, source_changes)
    refs = find_doc_references(config, source_changes)

    return DiffImpactReport(
        base_ref=base_ref,
        changed_source=source_changes,
        changed_docs=doc_changes,
        stale_shadows=stale,
        doc_references=refs,
    )


def format_diff_report(report: DiffImpactReport) -> str:
    """Format a diff impact report as human-readable text."""
    lines: list[str] = []
    lines.append(f"# Diff Impact Report (base: {report.base_ref})")
    lines.append("")

    if not report.changed_source and not report.changed_docs:
        lines.append("No changes found.")
        return "\n".join(lines)

    # Summary
    lines.append(f"**Changed**: {len(report.changed_source)} source file(s), {len(report.changed_docs)} doc file(s)")
    lines.append("")

    # Stale shadows
    if report.stale_shadows:
        lines.append("## Stale Shadow Documentation")
        lines.append("")
        for s in report.stale_shadows:
            if s.status == "deleted_source":
                label = "deleted source"
            elif s.status == "missing":
                label = "no shadow doc"
            else:
                label = "stale"
            lines.append(f"  [{label}] {s.source_path}")
        lines.append("")
        lines.append("Run `docstar shadow .` or `docstar diff <base> --update` to regenerate.")
        lines.append("")

    # Doc references
    if report.doc_references:
        lines.append("## Documentation References to Changed Source")
        lines.append("")
        for ref in report.doc_references:
            severity = "DELETED" if ref.source_deleted else "changed"
            lines.append(f"  [{severity}] {ref.doc_path}:{ref.line_number} -> {ref.source_path}")
            lines.append(f"           {ref.line_content}")
        lines.append("")
        lines.append("Review these documentation files - they may need updating.")
        lines.append("")

    # Result
    if report.has_issues:
        total = len(report.stale_shadows) + len(report.doc_references)
        lines.append(f"---\n**{total} issue(s) found.**")
    else:
        lines.append("---\n**No issues found.** Documentation appears in sync.")

    return "\n".join(lines)


def format_diff_json(report: DiffImpactReport) -> str:
    """Format a diff impact report as JSON."""
    return json.dumps({
        "base_ref": report.base_ref,
        "has_issues": report.has_issues,
        "changed_source": [
            {
                "path": str(c.path),
                "change_type": c.change_type,
            }
            for c in report.changed_source
        ],
        "changed_docs": [
            {
                "path": str(c.path),
                "change_type": c.change_type,
            }
            for c in report.changed_docs
        ],
        "stale_shadows": [
            {
                "source_path": str(s.source_path),
                "shadow_exists": s.shadow_exists,
                "status": s.status,
            }
            for s in report.stale_shadows
        ],
        "doc_references": [
            {
                "doc_path": str(r.doc_path),
                "source_path": str(r.source_path),
                "line_number": r.line_number,
                "line_content": r.line_content,
                "source_deleted": r.source_deleted,
            }
            for r in report.doc_references
        ],
    }, indent=2)
