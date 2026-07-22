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

``MIGRATION-REPORT.md``/``MIGRATION-SKIPPED.md`` are a deterministic function
of the manifest plus a fresh re-scan of ``_holding/`` — never of what this
particular invocation did (no "N newly migrated this run" counters, no
timestamps). Concretely: the write pass (which respects ``--only``) and the
report pass (which always re-validates the FULL manifest, ``--only`` or not)
are separate; see ``_validate_fixture_entry``/``_validate_audit_entry`` (the
shared, read-only validators both passes call) and ``_status_fixture_entry``/
``_status_audit_entry`` (the report pass's per-entry status). This is what
makes `git status` clean after any rerun over an unchanged tree, including a
targeted ``--only`` rerun of an already-migrated slug. A per-run summary
(newly migrated / already present / skipped, honoring ``--only``) prints to
stdout only — it is never written to a file, so it carries no determinism
obligation.

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
from dataclasses import dataclass, replace
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


def _case_already_handled(entry: dict[str, Any], dest: Path) -> bool:
    """True if this entry has a case dir under ``dest`` (the ordinary rerun
    case) OR has already been accepted out of holding into the live corpus
    (``<CORPUS_ROOT>/<category>/case_<NNN>_<slug>/`` per the corpus README's
    acceptance flow, which renames the directory and moves it out of
    ``_holding/`` entirely).

    Without this second check, a rerun over an unchanged manifest would see
    no ``case_<slug>`` dir left under ``_holding/<category>/`` for an
    accepted entry (it moved and was renamed) and treat it as never
    migrated — re-validating and re-writing a fresh ``accepted: false``
    holding copy right next to the one already accepted, silently
    resurrecting reviewed cases. Matching is by category + slug (the part
    of the accepted name after the ``case_<NNN>_`` prefix), independent of
    ``dest`` — acceptance always targets the real corpus root, never a
    ``--dest`` override.
    """

    if _case_dir_for(dest, entry).exists():
        return True
    category_dir = CORPUS_ROOT / entry["category"]
    if not category_dir.is_dir():
        return False
    return any(category_dir.glob(f"case_*_{entry['slug']}"))


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
#
# Validation (``_validate_*``) is pure and read-only: given an entry, it
# either returns what's needed to write a case, or a reason it can't. The
# same validator backs two callers that must never drift apart:
#
# - ``migrate_*_entry`` — the write path (respects ``--only``): validates,
#   then writes if validation succeeds and the case_dir doesn't already
#   exist.
# - ``_status_*_entry`` — the report path (always the FULL manifest,
#   independent of ``--only``): validates but never writes, so a case not
#   selected by this run's ``--only`` still gets an honest, deterministic
#   status rather than being silently absent from the report.
#
# This split exists because MIGRATION-REPORT.md/MIGRATION-SKIPPED.md must be
# a deterministic function of on-disk state + the manifest — NOT of which
# entries this particular invocation happened to touch or create. A rerun
# over an unchanged tree (with or without --only) must reproduce byte-
# identical report files.


class MigrationOutcome:
    __slots__ = ("status", "reason", "facts_written")

    def __init__(self, status: str, reason: str | None = None, facts_written: int = 0):
        self.status = status  # "migrated" | "exists" | "skipped"
        self.reason = reason
        self.facts_written = facts_written


@dataclass(frozen=True)
class _FixtureValidation:
    finding: Finding
    snapshot_ref: str
    stripped_path: str


def _validate_fixture_entry(entry: dict[str, Any]) -> tuple[_FixtureValidation | None, str | None]:
    """Pure/read-only: everything ``migrate_fixture_entry`` needs to know
    whether (and how) a fixture-origin entry can be written, without
    writing anything. Returns ``(validation, None)`` or ``(None, reason)``."""

    fixture_root = entry.get("fixture_root")
    if not fixture_root:
        return None, "fixture-origin entry has no fixture_root field"

    fixture_root_posix = _to_posix(fixture_root)
    if not (REPO_ROOT / fixture_root).is_dir():
        return None, f"fixture_root does not exist: {fixture_root_posix}"

    prefix = CORPUS_ROOT_REL + "/"
    if not fixture_root_posix.startswith(prefix):
        return None, f"fixture_root {fixture_root_posix!r} is not under {CORPUS_ROOT_REL}/"
    snapshot_ref = fixture_root_posix[len(prefix):]

    finding, err = _load_finding_or_none(entry["finding"])
    if finding is None:
        return None, err

    source_prefix = f"{fixture_root_posix}/source/"
    raw_path = _to_posix(finding.path)
    if not raw_path.startswith(source_prefix):
        return None, (
            f"finding.path {raw_path!r} does not start with {source_prefix!r} "
            "(fixture-relative path stripping assumption failed)"
        )
    stripped_path = raw_path[len(source_prefix):]

    return _FixtureValidation(finding, snapshot_ref, stripped_path), None


def migrate_fixture_entry(entry: dict[str, Any], dest: Path, adjudicated_at: str) -> MigrationOutcome:
    """fixture-origin (A): point at the existing legacy fixture dir via
    ``snapshot_ref`` — no new ``source/`` is written."""

    case_dir = _case_dir_for(dest, entry)
    if _case_already_handled(entry, dest):
        return MigrationOutcome(
            "exists", "case directory already exists (rerun) or already accepted into the "
            "corpus — left untouched"
        )

    validation, err = _validate_fixture_entry(entry)
    if validation is None:
        return MigrationOutcome("skipped", err)

    case_data = _build_case_json(
        entry,
        gap_type=validation.finding.gap_type,
        detector_producer=_producer_of(validation.finding.detector),
        language=_language_for(validation.stripped_path, None),
        snapshot_ref=validation.snapshot_ref,
        commit=None,  # a fixture-origin case has no single backing commit
        swept_at=adjudicated_at,
    )
    finding_data = _finding_for_case(validation.finding, path=validation.stripped_path)
    expected_data = _build_expected_json(entry, adjudicated_at)

    _write_json(case_dir / "case.json", case_data)
    _write_json(case_dir / "finding.json", finding_data)
    _write_json(case_dir / "expected.json", expected_data)

    return MigrationOutcome("migrated")


def _status_fixture_entry(entry: dict[str, Any], dest: Path) -> tuple[str, str | None]:
    """Report-path status for a fixture-origin entry — never writes.
    Returns ``("present", None)``, ``("skipped", reason)``, or
    ``("pending", reason)`` (validation would succeed but this destination
    has no case_dir for it yet — only possible when a prior run never
    covered it, e.g. an earlier ``--only`` excluded it). ``"present"`` also
    covers an entry already accepted out of ``_holding/`` into the live
    corpus (see ``_case_already_handled``) — it no longer has a case_dir
    under ``dest``, but is just as much "nothing to do" as a holding-dir
    rerun hit."""

    if _case_already_handled(entry, dest):
        return "present", None
    _, err = _validate_fixture_entry(entry)
    if err is None:
        return "pending", "validated OK but not yet migrated to this destination"
    return "skipped", err


@dataclass(frozen=True)
class _AuditValidation:
    finding: Finding
    finding_path: str
    relevant: frozenset[str]


def _validate_audit_entry(
    entry: dict[str, Any], commit: str
) -> tuple[_AuditValidation | None, str | None]:
    """Pure/read-only: everything ``migrate_audit_entry`` needs to know
    whether an audit-origin entry can be written, without fetching file
    bytes or writing anything (only cheap existence checks via ``git
    cat-file -e``). Returns ``(validation, None)`` or ``(None, reason)``."""

    finding, err = _load_finding_or_none(entry["finding"])
    if finding is None:
        return None, err

    finding_path = _to_posix(finding.path)
    if not _git_show_exists(commit, finding_path):
        return None, f"file does not exist at commit {commit}: {finding_path}"

    relevant = {finding_path} | _evidence_paths_at_commit(entry["finding"], commit)
    if len(relevant) > MAX_FILES:
        return None, (
            f"{len(relevant)} files exceeds the migration cap of {MAX_FILES} "
            "(snapshot-bloat guard)"
        )

    return _AuditValidation(finding, finding_path, frozenset(relevant)), None


def migrate_audit_entry(
    entry: dict[str, Any], dest: Path, commit: str, adjudicated_at: str
) -> MigrationOutcome:
    """audit-origin (B): snapshot the finding's file (+ evidence-referenced
    files) via ``git show <commit>:<path>``, then regenerate ``facts/``."""

    case_dir = _case_dir_for(dest, entry)
    if _case_already_handled(entry, dest):
        return MigrationOutcome(
            "exists", "case directory already exists (rerun) or already accepted into the "
            "corpus — left untouched"
        )

    validation, err = _validate_audit_entry(entry, commit)
    if validation is None:
        return MigrationOutcome("skipped", err)

    # Pre-flight: fetch every file's bytes before writing anything, so a
    # mid-way git failure never leaves a half-written case_dir behind.
    contents: dict[str, bytes] = {}
    for rel in sorted(validation.relevant):
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
            gap_type=validation.finding.gap_type,
            detector_producer=_producer_of(validation.finding.detector),
            language=_language_for(validation.finding_path, None),
            snapshot_ref=None,
            commit=commit,
            swept_at=adjudicated_at,
        )
        finding_data = _finding_for_case(validation.finding, path=validation.finding_path)
        expected_data = _build_expected_json(entry, adjudicated_at)

        _write_json(case_dir / "case.json", case_data)
        _write_json(case_dir / "finding.json", finding_data)
        _write_json(case_dir / "expected.json", expected_data)

        facts_written = _write_facts_sidecars(case_dir, source_root, adjudicated_at)
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise

    return MigrationOutcome("migrated", facts_written=len(facts_written))


def _status_audit_entry(entry: dict[str, Any], dest: Path, commit: str) -> tuple[str, str | None]:
    """Report-path status for an audit-origin entry — never writes, never
    fetches file bytes (existence checks only). See ``_status_fixture_entry``
    for the ``"pending"`` and already-accepted ``"present"`` semantics."""

    if _case_already_handled(entry, dest):
        return "present", None
    _, err = _validate_audit_entry(entry, commit)
    if err is None:
        return "pending", "validated OK but not yet migrated to this destination"
    return "skipped", err


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
#
# Everything below is a pure function of (a) the manifest and (b) a fresh
# re-scan of ``dest`` — never of "what this particular run did" (no counts
# of newly-created vs pre-existing, no timestamps). That's what makes
# MIGRATION-REPORT.md/MIGRATION-SKIPPED.md byte-identical across any number
# of reruns over an unchanged tree, regardless of ``--only``/``--commit``
# repetition.

#: One row per manifest entry, in the report's stable sort order.
StatusRow = tuple[str, str, str, str | None]  # (slug, class, status, reason)


def _status_rows(
    fixture_entries: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    fixture_status: dict[str, tuple[str, str | None]],
    audit_status: dict[str, tuple[str, str | None]],
) -> list[StatusRow]:
    rows: list[StatusRow] = [
        (e["slug"], "A", *fixture_status[e["slug"]]) for e in fixture_entries
    ] + [
        (e["slug"], "B", *audit_status[e["slug"]]) for e in audit_entries
    ]
    rows.sort(key=lambda r: r[0])
    return rows


def _count_facts_sidecars(dest: Path) -> int:
    """Deterministic re-scan: how many ``facts/*.facts.json`` files currently
    exist under ``dest`` — the current total, not "written by this run"."""

    return sum(1 for _ in dest.glob("*/case_*/facts/**/*.facts.json"))


def _render_report(
    *,
    manifest: dict[str, Any],
    commit: str,
    dest: Path,
    fixture_entries: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    fixture_status: dict[str, tuple[str, str | None]],
    audit_status: dict[str, tuple[str, str | None]],
    fixture_cross_check: list[str],
    audit_cross_check: list[str],
) -> str:
    def _tally(status: dict[str, tuple[str, str | None]]) -> tuple[int, int, int]:
        present = sum(1 for s, _ in status.values() if s == "present")
        skipped = sum(1 for s, _ in status.values() if s == "skipped")
        pending = sum(1 for s, _ in status.values() if s == "pending")
        return present, skipped, pending

    fx_present, fx_skipped, fx_pending = _tally(fixture_status)
    au_present, au_skipped, au_pending = _tally(audit_status)
    total_facts = _count_facts_sidecars(dest)

    lines: list[str] = []
    lines.append("# Bootstrap corpus migration report")
    lines.append("")
    lines.append(
        "Generated by `scripts/migrate_bootstrap_corpus.py` "
        "(V1-7 evaluator, Track 1 PR-6). This report is a deterministic "
        "function of the manifest and the current `_holding/` contents — "
        "not of what any one invocation did — so it is byte-identical "
        "across any number of reruns over an unchanged tree, `--only` or not."
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
    lines.append("## Summary (current state of `_holding/`, full manifest)")
    lines.append("")
    lines.append("| class | total | present | skipped | pending |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append(
        f"| A (fixture-origin) | {len(fixture_entries)} | {fx_present} | {fx_skipped} | {fx_pending} |"
    )
    lines.append(
        f"| B (audit-origin) | {len(audit_entries)} | {au_present} | {au_skipped} | {au_pending} |"
    )
    lines.append(
        f"| **total** | {len(fixture_entries) + len(audit_entries)} | {fx_present + au_present} "
        f"| {fx_skipped + au_skipped} | {fx_pending + au_pending} |"
    )
    lines.append("")
    lines.append(
        "`pending` = validated OK (would migrate cleanly) but no case_dir exists "
        "at this destination yet — only possible when a prior run's `--only` "
        "excluded an entry that has never otherwise been migrated; 0 in steady "
        "state. `present` cases were migrated at some point (this run or a "
        "prior one) — not distinguished here, since that distinction is "
        "run-history, not tree state."
    )
    lines.append("")
    lines.append(f"`facts/` sidecar files currently present under B cases: {total_facts}")
    lines.append("")

    lines.append("## Per-entry status (full manifest, sorted by slug)")
    lines.append("")
    for slug, cls, status, reason in _status_rows(
        fixture_entries, audit_entries, fixture_status, audit_status
    ):
        if status == "present":
            lines.append(f"- `{slug}` ({cls}): migrated")
        elif status == "pending":
            lines.append(f"- `{slug}` ({cls}): pending — {reason}")
        else:
            lines.append(f"- `{slug}` ({cls}): skipped — {reason}")
    lines.append("")

    lines.append("## Skipped entries")
    lines.append("")
    skipped_rows = [
        (slug, cls, reason)
        for slug, cls, status, reason in _status_rows(
            fixture_entries, audit_entries, fixture_status, audit_status
        )
        if status == "skipped"
    ]
    if skipped_rows:
        for slug, cls, reason in skipped_rows:
            lines.append(f"- `{slug}` ({cls}): {reason}")
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


def _render_skipped_md(
    fixture_entries: list[dict[str, Any]],
    audit_entries: list[dict[str, Any]],
    fixture_status: dict[str, tuple[str, str | None]],
    audit_status: dict[str, tuple[str, str | None]],
) -> str:
    lines = ["# Skipped bootstrap-manifest entries", ""]
    rows = [
        (slug, cls, reason)
        for slug, cls, status, reason in _status_rows(
            fixture_entries, audit_entries, fixture_status, audit_status
        )
        if status == "skipped"
    ]
    if not rows:
        lines.append("(none)")
    else:
        for slug, cls, reason in rows:
            lines.append(f"- `{slug}` ({cls}): {reason}")
    return "\n".join(lines) + "\n"


def _render_run_summary(
    *,
    only: set[str],
    fixture_write_outcomes: dict[str, MigrationOutcome],
    audit_write_outcomes: dict[str, MigrationOutcome],
) -> str:
    """A transient, stdout-only summary of THIS invocation's write pass
    (newly migrated vs already-present vs skipped, within ``--only``'s
    scope if given) — never written to any file, so it carries no
    determinism obligation. The committed reports are built from
    ``_status_rows`` instead, which always re-scans the full manifest."""

    all_outcomes = {**fixture_write_outcomes, **audit_write_outcomes}
    new = sorted(slug for slug, o in all_outcomes.items() if o.status == "migrated")
    existing = sorted(slug for slug, o in all_outcomes.items() if o.status == "exists")
    skipped = sorted(slug for slug, o in all_outcomes.items() if o.status == "skipped")

    lines = ["--- this run ---"]
    if only:
        lines.append(f"--only scope: {len(only)} slug(s)")
    lines.append(
        f"newly migrated: {len(new)}, already present: {len(existing)}, skipped: {len(skipped)}"
    )
    if new:
        lines.append(f"  new: {', '.join(new)}")
    lines.append("(MIGRATION-REPORT.md/MIGRATION-SKIPPED.md reflect the full manifest, not just this run)")
    return "\n".join(lines)


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
    dest.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(args.manifest)
    commit = args.commit or manifest.get("commit")
    if not commit:
        print("error: no --commit given and manifest has no 'commit' field", file=sys.stderr)
        return 1

    adjudicated_at = _iso_from_manifest_date(manifest.get("audited"))

    all_entries = manifest["entries"]
    all_fixture_entries = [e for e in all_entries if e["origin"] == "fixture"]
    all_audit_entries = [e for e in all_entries if e["origin"] == "audit"]

    # --- write pass: respects --only, may create case dirs -----------------
    only = _parse_only(args.only)
    write_entries = all_entries
    if only:
        write_entries = [e for e in all_entries if e["slug"] in only]
        unknown = only - {e["slug"] for e in write_entries}
        if unknown:
            print(f"warning: --only names unknown slugs: {sorted(unknown)}", file=sys.stderr)

    fixture_write_outcomes: dict[str, MigrationOutcome] = {}
    for entry in write_entries:
        if entry["origin"] == "fixture":
            fixture_write_outcomes[entry["slug"]] = migrate_fixture_entry(entry, dest, adjudicated_at)

    audit_write_outcomes: dict[str, MigrationOutcome] = {}
    for entry in write_entries:
        if entry["origin"] == "audit":
            audit_write_outcomes[entry["slug"]] = migrate_audit_entry(
                entry, dest, commit, adjudicated_at
            )

    print(
        _render_run_summary(
            only=only,
            fixture_write_outcomes=fixture_write_outcomes,
            audit_write_outcomes=audit_write_outcomes,
        )
    )
    print()

    # --- report pass: ALWAYS the full manifest, never writes, independent
    # of --only -- this is what makes the committed reports a deterministic
    # function of on-disk state rather than of this invocation's write scope.
    fixture_status = {e["slug"]: _status_fixture_entry(e, dest) for e in all_fixture_entries}
    audit_status = {e["slug"]: _status_audit_entry(e, dest, commit) for e in all_audit_entries}

    fixture_cross_check = _cross_check(manifest, MANIFEST_FIXTURES, "fixture")
    audit_cross_check = _cross_check(manifest, MANIFEST_AUDIT, "audit")

    report = _render_report(
        manifest=manifest,
        commit=commit,
        dest=dest,
        fixture_entries=all_fixture_entries,
        audit_entries=all_audit_entries,
        fixture_status=fixture_status,
        audit_status=audit_status,
        fixture_cross_check=fixture_cross_check,
        audit_cross_check=audit_cross_check,
    )
    print(report)

    (dest / "MIGRATION-REPORT.md").write_text(report, encoding="utf-8", newline="\n")
    (dest / "MIGRATION-SKIPPED.md").write_text(
        _render_skipped_md(all_fixture_entries, all_audit_entries, fixture_status, audit_status),
        encoding="utf-8",
        newline="\n",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
