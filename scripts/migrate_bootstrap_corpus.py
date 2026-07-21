"""Bootstrap corpus migration (V1-7 evaluator, Track 1 PR-6).

The 54-entry bootstrap manifest (``tests/fixtures/bootstrap/manifest.json``,
format documented at the top of ``scripts/triage_bootstrap.py``) carries
human-adjudicated verdicts, but its findings reference the live osoji tree —
``origin: "fixture"`` entries point at a legacy fixture directory that could
drift, and ``origin: "audit"`` entries point at repo-relative paths as they
stood at the manifest's own pinned commit. Neither is a self-contained
``corpus-case/1`` (``tests/fixtures/prompt_regression/README.md``): the corpus
format exists precisely so a case replays the same way forever, independent
of what the live tree looks like on replay day.

This script is a one-time (but rerunnable) mechanical migration, zero LLM
calls, fully deterministic (no wall-clock timestamps — every date-bearing
field is derived from the manifest's own ``audited`` date so a from-scratch
rerun reproduces byte-identical output):

- **fixture-origin entries** (``origin: "fixture"``) already have a
  self-contained snapshot on disk (the legacy fixture directory under
  ``tests/fixtures/prompt_regression/``) — the migrated case points at it via
  ``snapshot_ref`` rather than copying it again.
- **audit-origin entries** (``origin: "audit"``) get their finding's own file
  (plus any evidence-referenced files, mechanically) snapshotted via
  ``git show <commit>:<path>`` into a fresh ``source/`` tree (CRLF/CR
  normalized to LF — see ``_normalize_snapshot_bytes`` — so the on-disk
  result and its ``source_hash`` don't depend on the committer's
  ``core.autocrlf`` setting), so the case no longer depends on the live
  tree at all. Deterministic ``facts/`` sidecars
  are regenerated over that snapshot via the Python plugin's tree-sitter
  extraction (``extraction_method: "ast"``, no LLM) — see the module
  docstring note on ``symbols/`` below for why those are NOT regenerated.

Every migrated case lands under ``_holding/<category>/case_<slug>/`` with
``expected.json["accepted"] = false`` — nothing here is wired into
``load_corpus`` until a human reviews it and flips ``accepted``, per the
corpus README's acceptance flow. This script never modifies
``tests/fixtures/bootstrap/`` (manifest, legacy fixture dirs) or
``splits.json`` — split assignment happens at acceptance, not migration.

Symbols sidecars: ``.osoji/symbols/*.symbols.json`` carries LLM-assigned
``file_role`` and per-symbol ``visibility`` (see ``shadow.py``'s
``generate_file_shadow_doc_async``) — there is no mechanical/AST-only
entry point that produces that shape (the tree-sitter plugin's
``extract_project_facts`` produces ``facts`` structural data — imports,
exports, calls, member_writes, string_literals — not symbol visibility
classification). Investigated per the migration brief's sanctioned
fallback: symbols/ sidecars are skipped entirely for every migrated case
(evidence rebuild works from the ``source/`` text alone; sidecars are always
optional per the corpus README). ``shadow/`` sidecars are skipped
unconditionally too (LLM-only, no mechanical entry point at all).

Usage::

    python scripts/migrate_bootstrap_corpus.py
    python scripts/migrate_bootstrap_corpus.py --only dead_code-case_001-get_file_tools
    python scripts/migrate_bootstrap_corpus.py --dest tests/fixtures/prompt_regression/_holding
    python scripts/migrate_bootstrap_corpus.py --commit 94b689e
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from triage_bootstrap import load_manifest  # noqa: E402

from osoji import __version__  # noqa: E402
from osoji.corpus_emit import (  # noqa: E402
    CORPUS_CASE_SCHEMA,
    CORPUS_EXPECTED_SCHEMA,
    MAX_FILES,
    _git,
    _language_for,
    _posix_join,
    _producer_of,
    _to_posix,
    _walk_strings,
    _write_json,
)
from osoji.findings import Finding  # noqa: E402
from osoji.hasher import compute_file_hash  # noqa: E402
from osoji.plugins.base import FactsExtractionError, PluginUnavailableError  # noqa: E402
from osoji.plugins.python_plugin import PythonPlugin  # noqa: E402

BOOTSTRAP_DIR = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
DEFAULT_MANIFEST = BOOTSTRAP_DIR / "manifest.json"
MANIFEST_FIXTURES = BOOTSTRAP_DIR / "manifest-fixtures.json"
MANIFEST_AUDIT = BOOTSTRAP_DIR / "manifest-audit.json"

CORPUS_ROOT = REPO_ROOT / "tests" / "fixtures" / "prompt_regression"
CORPUS_ROOT_REL = "tests/fixtures/prompt_regression"
DEFAULT_DEST = CORPUS_ROOT / "_holding"

#: Fallback adjudication timestamp, only used if the manifest carries no
#: top-level "audited" date (ours does: "2026-07-01").
FALLBACK_ADJUDICATED_AT = "2026-07-03T00:00:00Z"
ADJUDICATED_BY = "bootstrap-manifest"
SWEEP_RUN = "bootstrap-manifest-migration"

# Triage-output fields a corpus case must null out (never store a stale
# verdict) — mirrors corpus_emit.emit_case's own field list exactly.
_TRIAGE_OUTPUT_FIELDS = (
    "verdict",
    "confidence",
    "triage_reasoning",
    "suggested_fix",
    "severity",
    "contract_class",
    "evidence_fingerprint",
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _iso_from_manifest_date(date_str: str | None) -> str:
    """``"2026-07-01"`` -> ``"2026-07-01T00:00:00Z"``; the fallback otherwise."""

    if not date_str:
        return FALLBACK_ADJUDICATED_AT
    return f"{date_str}T00:00:00Z"


def _adjudicated_reasoning(entry: dict[str, Any]) -> str:
    """``expected.json["reasoning"]``: ``adjudication_notes``, plus a later
    ``adjudication_reasoning`` re-adjudication when the manifest carries one.

    Two manifest entries (``audit-obligation_implicit_contract-001``/``-002``)
    carry both fields — ``adjudication_reasoning`` records a 2026-07-05
    re-adjudication that in one case (``-002``) flips the verdict itself
    (confirmed -> dismissed; see ``manifest-audit.json`` vs ``manifest.json``).
    Using ``adjudication_notes`` alone there would ship a "dismissed" verdict
    next to reasoning text that argues for "confirmed" — an incoherent
    corpus-expected/1 entry. Appending (never replacing) keeps the literal
    "reasoning=adjudication_notes" mapping intact while fixing that
    coherence bug; see MIGRATION-REPORT.md for the flagged slugs.
    """

    notes = entry.get("adjudication_notes", "")
    extra = entry.get("adjudication_reasoning")
    if extra:
        return f"{notes}\n\n{extra}"
    return notes


def _load_finding_or_none(finding_blob: dict[str, Any]) -> tuple[Finding | None, str | None]:
    """``Finding.from_dict`` round-trip check — the B skip criterion the
    brief names, applied uniformly to A entries too (defensive, cheap)."""

    try:
        finding = Finding.from_dict(finding_blob)
        round_tripped = Finding.from_dict(finding.to_dict())
    except Exception as exc:  # noqa: BLE001 - reported as a skip reason, not raised
        return None, f"finding blob failed Finding.from_dict round-trip: {exc}"
    if round_tripped.id != finding.id:
        return None, "finding blob's id did not survive a Finding.from_dict/to_dict round-trip"
    return finding, None


def _finding_for_case(finding: Finding, *, path: str) -> dict[str, Any]:
    """The corpus finding.json shape: triage outputs + evidence nulled, path
    rewritten to be snapshot-relative. ``id`` survives via ``replace`` (never
    recomputed — ``Finding.__post_init__`` only fills an empty id)."""

    stripped = replace(
        finding,
        path=path,
        evidence=[],
        **{field: None for field in _TRIAGE_OUTPUT_FIELDS},
    )
    return stripped.to_dict()


def _build_case_json(
    entry: dict[str, Any],
    *,
    gap_type: str | None,
    detector_producer: str,
    language: str,
    snapshot_ref: str | None,
    commit: str | None,
    swept_at: str,
) -> dict[str, Any]:
    return {
        "schema": CORPUS_CASE_SCHEMA,
        "slug": entry["slug"],
        "category": entry["category"],
        "detector": detector_producer,
        "gap_type": gap_type,
        "language": language,
        "origin": {
            "repo": "osoji",
            "remote": _git(["remote", "get-url", "origin"], REPO_ROOT),
            "commit": commit,
            "swept_at": swept_at,
            "osoji_version": __version__,
            "sweep_run": SWEEP_RUN,
        },
        "snapshot_ref": snapshot_ref,
        "evidence_policy": "rebuild",
    }


def _build_expected_json(entry: dict[str, Any], adjudicated_at: str) -> dict[str, Any]:
    return {
        "schema": CORPUS_EXPECTED_SCHEMA,
        "verdict": entry["adjudicated_verdict"],
        "reasoning": _adjudicated_reasoning(entry),
        "gray": bool(entry.get("gray", False)),
        "gray_reason": entry.get("gray_reason"),
        "expected_contract_class": None,
        "adjudicated_by": ADJUDICATED_BY,
        "adjudicated_at": adjudicated_at,
        "accepted": False,
    }


def _case_dir_for(dest: Path, entry: dict[str, Any]) -> Path:
    return dest / entry["category"] / f"case_{entry['slug']}"


# ---------------------------------------------------------------------------
# git-show snapshotting (audit-origin entries)
# ---------------------------------------------------------------------------


def _git_show_exists(commit: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.returncode == 0


def _git_show_bytes(commit: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _normalize_snapshot_bytes(data: bytes) -> bytes:
    """Normalize CRLF/CR line endings to LF for UTF-8-decodable content.

    A handful of files at commit 94b689e are stored with CRLF endings (a
    historical artifact — this repo otherwise commits LF, per README/CLAUDE.md
    convention). ``git show`` returns those blob bytes verbatim, bypassing any
    checkout-time smudge filter — but ``git add`` still applies its own
    checkin ("clean") filter under ``core.autocrlf=true``, which would
    silently rewrite those bytes to LF *after* this script already computed
    ``source_hash`` and wrote the "byte-identical" snapshot, making both
    wrong and making the result depend on the committer's local git config.
    Normalizing here — before hashing, before writing — makes the on-disk
    snapshot match what every clone (any ``core.autocrlf`` setting, any OS)
    will actually check out, independent of this repo's line-ending history.
    Content that isn't valid UTF-8 (shouldn't occur for this manifest's
    Python/doc sources, but the evidence-path scan is generic) passes
    through unchanged rather than risk corrupting binary data.
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _safe_relative_posix(raw: str) -> str | None:
    """POSIX-normalize ``raw``; ``None`` if it looks absolute or escapes via ``..``."""

    if not raw or "\x00" in raw:
        return None
    posix = _to_posix(raw)
    if posix.startswith("/"):
        return None
    if any(part == ".." for part in posix.split("/")):
        return None
    return posix


def _evidence_paths_at_commit(finding_blob: dict[str, Any], commit: str) -> set[str]:
    """Mechanical walk of ``finding["evidence"]`` payload strings that exist
    at ``commit`` — the same rule ``corpus_emit._evidence_paths`` applies to
    the live tree, adapted to check existence via ``git show`` instead of the
    filesystem (the whole point of this migration is to stop trusting the
    live tree). Every manifest entry's evidence is currently ``[]`` (nulled
    per the bootstrap harness convention), so this is a no-op in practice
    today but keeps the migration correct if that ever changes.
    """

    found: set[str] = set()
    for ev in finding_blob.get("evidence") or []:
        payload = ev.get("payload") if isinstance(ev, dict) else None
        if not isinstance(payload, dict):
            continue
        for s in _walk_strings(payload):
            posix = _safe_relative_posix(s)
            if posix and _git_show_exists(commit, posix):
                found.add(posix)
    return found


# ---------------------------------------------------------------------------
# facts/ sidecar regeneration (audit-origin entries only — see module
# docstring for why symbols/ and shadow/ are skipped)
# ---------------------------------------------------------------------------


def _write_facts_sidecars(case_dir: Path, source_root: Path, generated_at: str) -> list[str]:
    """Regenerate ``facts/<relpath>.facts.json`` for every Python file under
    ``source_root`` via the tree-sitter plugin (``extraction_method: "ast"``,
    zero LLM calls). Returns the list of relative paths written (``[]`` if
    the plugin is unavailable or there are no Python files to extract).
    """

    py_files = sorted(source_root.rglob("*.py"))
    if not py_files:
        return []

    plugin = PythonPlugin()
    try:
        plugin.check_available(source_root)
    except PluginUnavailableError:
        return []

    try:
        extracted = plugin.extract_project_facts(source_root, py_files)
    except FactsExtractionError:
        return []

    written: list[str] = []
    for rel_path, facts in sorted(extracted.items()):
        source_hash = compute_file_hash(source_root / rel_path)
        facts_dict: dict[str, Any] = {
            "source": rel_path,
            "source_hash": source_hash,
            "generated": generated_at,
            "imports": facts.imports,
            "exports": facts.exports,
            "calls": facts.calls,
            "member_writes": facts.member_writes,
        }
        if facts.string_literals is not None:
            facts_dict["string_literals"] = facts.string_literals
        facts_dict["extraction_method"] = "ast"

        facts_path = _posix_join(case_dir, f"facts/{rel_path}.facts.json")
        _write_json(facts_path, facts_dict)
        written.append(rel_path)

    return written


# ---------------------------------------------------------------------------
# per-entry migration
# ---------------------------------------------------------------------------


class MigrationOutcome:
    __slots__ = ("status", "reason", "facts_written")

    def __init__(self, status: str, reason: str | None = None, facts_written: int = 0):
        self.status = status  # "migrated" | "exists" | "skipped"
        self.reason = reason
        self.facts_written = facts_written


def migrate_fixture_entry(entry: dict[str, Any], dest: Path, adjudicated_at: str) -> MigrationOutcome:
    """fixture-origin (A): point at the existing legacy fixture dir via
    ``snapshot_ref`` — no new ``source/`` is written."""

    case_dir = _case_dir_for(dest, entry)
    if case_dir.exists():
        return MigrationOutcome("exists", "case directory already exists (rerun) — left untouched")

    fixture_root = entry.get("fixture_root")
    if not fixture_root:
        return MigrationOutcome("skipped", "fixture-origin entry has no fixture_root field")

    fixture_root_posix = _to_posix(fixture_root)
    if not (REPO_ROOT / fixture_root).is_dir():
        return MigrationOutcome("skipped", f"fixture_root does not exist: {fixture_root_posix}")

    prefix = CORPUS_ROOT_REL + "/"
    if not fixture_root_posix.startswith(prefix):
        return MigrationOutcome(
            "skipped", f"fixture_root {fixture_root_posix!r} is not under {CORPUS_ROOT_REL}/"
        )
    snapshot_ref = fixture_root_posix[len(prefix):]

    finding, err = _load_finding_or_none(entry["finding"])
    if finding is None:
        return MigrationOutcome("skipped", err)

    source_prefix = f"{fixture_root_posix}/source/"
    raw_path = _to_posix(finding.path)
    if not raw_path.startswith(source_prefix):
        return MigrationOutcome(
            "skipped",
            f"finding.path {raw_path!r} does not start with {source_prefix!r} "
            "(fixture-relative path stripping assumption failed)",
        )
    stripped_path = raw_path[len(source_prefix):]

    case_data = _build_case_json(
        entry,
        gap_type=finding.gap_type,
        detector_producer=_producer_of(finding.detector),
        language=_language_for(stripped_path, None),
        snapshot_ref=snapshot_ref,
        commit=None,  # a fixture-origin case has no single backing commit
        swept_at=adjudicated_at,
    )
    finding_data = _finding_for_case(finding, path=stripped_path)
    expected_data = _build_expected_json(entry, adjudicated_at)

    _write_json(case_dir / "case.json", case_data)
    _write_json(case_dir / "finding.json", finding_data)
    _write_json(case_dir / "expected.json", expected_data)

    return MigrationOutcome("migrated")


def migrate_audit_entry(
    entry: dict[str, Any], dest: Path, commit: str, adjudicated_at: str
) -> MigrationOutcome:
    """audit-origin (B): snapshot the finding's file (+ evidence-referenced
    files) via ``git show <commit>:<path>``, then regenerate ``facts/``."""

    case_dir = _case_dir_for(dest, entry)
    if case_dir.exists():
        return MigrationOutcome("exists", "case directory already exists (rerun) — left untouched")

    finding, err = _load_finding_or_none(entry["finding"])
    if finding is None:
        return MigrationOutcome("skipped", err)

    finding_path = _to_posix(finding.path)
    if not _git_show_exists(commit, finding_path):
        return MigrationOutcome(
            "skipped", f"file does not exist at commit {commit}: {finding_path}"
        )

    relevant = {finding_path} | _evidence_paths_at_commit(entry["finding"], commit)
    if len(relevant) > MAX_FILES:
        return MigrationOutcome(
            "skipped",
            f"{len(relevant)} files exceeds the migration cap of {MAX_FILES} "
            "(snapshot-bloat guard)",
        )

    # Pre-flight: fetch every file's bytes before writing anything, so a
    # mid-way git failure never leaves a half-written case_dir behind.
    contents: dict[str, bytes] = {}
    for rel in sorted(relevant):
        data = _git_show_bytes(commit, rel)
        if data is None:
            return MigrationOutcome(
                "skipped", f"git show {commit}:{rel} failed after existence check succeeded"
            )
        contents[rel] = _normalize_snapshot_bytes(data)

    try:
        source_root = case_dir / "source"
        for rel, data in contents.items():
            dest_file = _posix_join(source_root, rel)
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(data)

        case_data = _build_case_json(
            entry,
            gap_type=finding.gap_type,
            detector_producer=_producer_of(finding.detector),
            language=_language_for(finding_path, None),
            snapshot_ref=None,
            commit=commit,
            swept_at=adjudicated_at,
        )
        finding_data = _finding_for_case(finding, path=finding_path)
        expected_data = _build_expected_json(entry, adjudicated_at)

        _write_json(case_dir / "case.json", case_data)
        _write_json(case_dir / "finding.json", finding_data)
        _write_json(case_dir / "expected.json", expected_data)

        facts_written = _write_facts_sidecars(case_dir, source_root, adjudicated_at)
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise

    return MigrationOutcome("migrated", facts_written=len(facts_written))


# ---------------------------------------------------------------------------
# cross-checks (informational; never fatal)
# ---------------------------------------------------------------------------


def _cross_check(manifest: dict[str, Any], split_path: Path, origin: str) -> list[str]:
    """Compare ``manifest``'s ``origin``-filtered slugs/content against the
    corresponding split file (``manifest-fixtures.json`` / ``manifest-audit.json``).
    Returns human-readable discrepancy lines (empty means an exact match)."""

    if not split_path.exists():
        return [f"{split_path.name} not found — cross-check skipped"]

    split_data = load_manifest(split_path)
    split_entries = split_data.get("entries", [])
    split_by_slug = {e["slug"]: e for e in split_entries}

    main_by_slug = {e["slug"]: e for e in manifest["entries"] if e["origin"] == origin}

    lines: list[str] = []
    missing = sorted(set(main_by_slug) - set(split_by_slug))
    extra = sorted(set(split_by_slug) - set(main_by_slug))
    if missing:
        lines.append(f"in manifest.json but not {split_path.name}: {missing}")
    if extra:
        lines.append(f"in {split_path.name} but not manifest.json ({origin}-origin): {extra}")

    content_mismatches = sorted(
        slug
        for slug in (set(main_by_slug) & set(split_by_slug))
        if main_by_slug[slug] != split_by_slug[slug]
    )
    if content_mismatches:
        lines.append(
            f"content differs from {split_path.name} for {len(content_mismatches)} slug(s) "
            f"(manifest.json is authoritative — newer adjudication metadata): "
            + ", ".join(content_mismatches)
        )

    return lines


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def _render_report(
    *,
    manifest: dict[str, Any],
    commit: str,
    dest: Path,
    fixture_outcomes: dict[str, MigrationOutcome],
    audit_outcomes: dict[str, MigrationOutcome],
    fixture_cross_check: list[str],
    audit_cross_check: list[str],
) -> str:
    def _tally(outcomes: dict[str, MigrationOutcome]) -> tuple[int, int, int]:
        migrated = sum(1 for o in outcomes.values() if o.status == "migrated")
        exists = sum(1 for o in outcomes.values() if o.status == "exists")
        skipped = sum(1 for o in outcomes.values() if o.status == "skipped")
        return migrated, exists, skipped

    fx_migrated, fx_exists, fx_skipped = _tally(fixture_outcomes)
    au_migrated, au_exists, au_skipped = _tally(audit_outcomes)
    total_facts = sum(o.facts_written for o in audit_outcomes.values())

    lines: list[str] = []
    lines.append("# Bootstrap corpus migration report")
    lines.append("")
    lines.append(
        "Generated by `scripts/migrate_bootstrap_corpus.py` "
        "(V1-7 evaluator, Track 1 PR-6)."
    )
    lines.append("")
    lines.append("- Manifest: `tests/fixtures/bootstrap/manifest.json`")
    lines.append(f"  - manifest commit: `{manifest.get('commit')}`, audited: `{manifest.get('audited')}`")
    lines.append(f"- Migration commit (audit-origin snapshots): `{commit}`")
    try:
        dest_display = dest.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        dest_display = str(dest)
    lines.append(f"- Destination: `{dest_display}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| class | total | migrated | already existed (rerun) | skipped |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| A (fixture-origin) | {len(fixture_outcomes)} | {fx_migrated} | {fx_exists} | {fx_skipped} |"
    )
    lines.append(
        f"| B (audit-origin) | {len(audit_outcomes)} | {au_migrated} | {au_exists} | {au_skipped} |"
    )
    lines.append(
        f"| **total** | {len(fixture_outcomes) + len(audit_outcomes)} | {fx_migrated + au_migrated} "
        f"| {fx_exists + au_exists} | {fx_skipped + au_skipped} |"
    )
    lines.append("")
    lines.append(f"`facts/` sidecar files written across B cases: {total_facts}")
    lines.append("")

    lines.append("## Skipped entries")
    lines.append("")
    skipped_lines = [
        (slug, "A", o.reason) for slug, o in sorted(fixture_outcomes.items()) if o.status == "skipped"
    ] + [
        (slug, "B", o.reason) for slug, o in sorted(audit_outcomes.items()) if o.status == "skipped"
    ]
    if skipped_lines:
        for slug, cls, reason in skipped_lines:
            lines.append(f"- `{slug}` ({cls}): {reason}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Already-existing cases (rerun, left untouched)")
    lines.append("")
    exists_lines = [
        slug for slug, o in sorted({**fixture_outcomes, **audit_outcomes}.items()) if o.status == "exists"
    ]
    if exists_lines:
        for slug in exists_lines:
            lines.append(f"- `{slug}`")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Cross-check: manifest.json vs the split manifests")
    lines.append("")
    lines.append("### manifest-fixtures.json (fixture-origin subset)")
    lines.append("")
    for line in fixture_cross_check or ["exact match — no discrepancies"]:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("### manifest-audit.json (audit-origin subset)")
    lines.append("")
    for line in audit_cross_check or ["exact match — no discrepancies"]:
        lines.append(f"- {line}")
    lines.append("")

    lines.append("## Sidecar extraction (audit-origin only)")
    lines.append("")
    lines.append(
        "`facts/` sidecars are regenerated deterministically via "
        "`osoji.plugins.python_plugin.PythonPlugin.extract_project_facts` "
        "(tree-sitter, `extraction_method: \"ast\"`, zero LLM calls) for every "
        "`.py` file under each migrated case's `source/`. `symbols/` and "
        "`shadow/` sidecars are skipped entirely — investigated, not forced: "
        "`.osoji/symbols/*.symbols.json` requires LLM-assigned `file_role` and "
        "per-symbol `visibility` (`shadow.py`'s `generate_file_shadow_doc_async`); "
        "no mechanical/AST-only entry point produces that shape. Sidecars are "
        "always optional per the corpus README — evidence rebuild works from "
        "`source/` text alone."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def _render_skipped_md(fixture_outcomes: dict[str, MigrationOutcome], audit_outcomes: dict[str, MigrationOutcome]) -> str:
    lines = ["# Skipped bootstrap-manifest entries", ""]
    rows = [
        (slug, "A", o.reason) for slug, o in sorted(fixture_outcomes.items()) if o.status == "skipped"
    ] + [
        (slug, "B", o.reason) for slug, o in sorted(audit_outcomes.items()) if o.status == "skipped"
    ]
    if not rows:
        lines.append("(none — every entry either migrated or already existed from a prior run)")
    else:
        for slug, cls, reason in rows:
            lines.append(f"- `{slug}` ({cls}): {reason}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_only(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {slug.strip() for slug in raw.split(",") if slug.strip()}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", type=str, default=None, help="comma-separated slugs to restrict migration to"
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="corpus holding directory (default: tests/fixtures/prompt_regression/_holding)",
    )
    parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="commit to snapshot audit-origin entries from (default: the manifest's own 'commit' field)",
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST, help="bootstrap manifest.json path"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    dest = args.dest if args.dest.is_absolute() else REPO_ROOT / args.dest
    manifest = load_manifest(args.manifest)
    commit = args.commit or manifest.get("commit")
    if not commit:
        print("error: no --commit given and manifest has no 'commit' field", file=sys.stderr)
        return 1

    adjudicated_at = _iso_from_manifest_date(manifest.get("audited"))

    only = _parse_only(args.only)
    entries = manifest["entries"]
    if only:
        entries = [e for e in entries if e["slug"] in only]
        unknown = only - {e["slug"] for e in entries}
        if unknown:
            print(f"warning: --only names unknown slugs: {sorted(unknown)}", file=sys.stderr)

    fixture_entries = [e for e in entries if e["origin"] == "fixture"]
    audit_entries = [e for e in entries if e["origin"] == "audit"]

    fixture_outcomes: dict[str, MigrationOutcome] = {}
    for entry in fixture_entries:
        fixture_outcomes[entry["slug"]] = migrate_fixture_entry(entry, dest, adjudicated_at)

    audit_outcomes: dict[str, MigrationOutcome] = {}
    for entry in audit_entries:
        audit_outcomes[entry["slug"]] = migrate_audit_entry(entry, dest, commit, adjudicated_at)

    fixture_cross_check = _cross_check(manifest, MANIFEST_FIXTURES, "fixture")
    audit_cross_check = _cross_check(manifest, MANIFEST_AUDIT, "audit")

    report = _render_report(
        manifest=manifest,
        commit=commit,
        dest=dest,
        fixture_outcomes=fixture_outcomes,
        audit_outcomes=audit_outcomes,
        fixture_cross_check=fixture_cross_check,
        audit_cross_check=audit_cross_check,
    )
    print(report)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "MIGRATION-REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    (dest / "MIGRATION-SKIPPED.md").write_text(
        _render_skipped_md(fixture_outcomes, audit_outcomes), encoding="utf-8", newline="\n"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
