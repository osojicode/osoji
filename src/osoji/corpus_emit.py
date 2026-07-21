"""osoji corpus emit -- snapshot one decided finding into a corpus-case/1 stub.

Bridges live audits to the V1-7 evaluator's fixture corpus
(``tests/fixtures/prompt_regression/README.md``, osojicode/work#35). Every
``osoji audit`` run writes a decided-findings ledger
(``.osoji/analysis/decided-findings.json`` -- see ``audit.py``'s
``run_audit_async`` and ``triage.py``'s ``Triage.decide_batch``); this module
turns one ledger entry into a review-ready ``_holding/`` case directory that
a human can accept into the corpus with ``git mv``.

Pure function core (:func:`emit_case`) plus small I/O helpers; ``cli.py``
wraps this in a thin ``osoji corpus emit`` Click command. This module must
work when osoji is installed as a wheel in an arbitrary repo -- unlike
``scripts/eval_lib.py`` (which is not shipped), it cannot assume it is
running inside the osoji checkout.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .audit import _CLI_FLAG_TO_PRODUCER, _JUNK_NAME_TO_CLI_FLAG
from .config import SHADOW_DIR

CORPUS_CASE_SCHEMA = "corpus-case/1"
CORPUS_EXPECTED_SCHEMA = "corpus-expected/1"
# Mirrors the literal schema tag audit.py's run_audit_async writes into
# .osoji/analysis/decided-findings.json. Not imported from audit.py (that
# would be a needless coupling to a single string) -- kept here since this is
# the module that reads the ledger back.
DECIDED_FINDINGS_SCHEMA = "decided-findings/1"

#: Env var honored by ``resolve_dest`` when --dest is not given.
ENV_CORPUS_DEST = "OSOJI_CORPUS_DEST"

#: Snapshot-bloat guard (deliverable 2, point 2): a claim whose evidence
#: mentions dozens of files is a sign the selection needs narrowing, not a
#: case that should snapshot half the repo.
MAX_FILES = 25

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")

#: (sidecar subdirectory, filename suffix) pairs, mirroring config.py's
#: symbols_path_for / facts_path_for / shadow_path_for conventions
#: (<repo-relative-path> + suffix, rooted under .osoji/<subdir>/).
_SIDECARS: tuple[tuple[str, str], ...] = (
    ("symbols", ".symbols.json"),
    ("facts", ".facts.json"),
    ("shadow", ".shadow.md"),
)

#: Minimal extension -> language-label mapping for case.json metadata.
#: Labeling only -- no behavior in this module or in eval_lib depends on it.
_EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}


class CorpusEmitError(Exception):
    """A user-facing ``emit_case``/``resolve_dest`` failure (clear message)."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _to_posix(value: str) -> str:
    """Normalize a possibly-Windows-separated relative path to POSIX."""

    return PurePosixPath(str(value).replace("\\", "/")).as_posix()


def _posix_join(base: Path, rel: str) -> Path:
    """Join a POSIX-separated relative path onto ``base`` (Windows-safe).

    Splits on the literal ``/`` separator rather than trusting ``Path``'s
    platform-native parsing, mirroring ``eval_lib._resolve_posix_ref``.
    """

    parts = [p for p in rel.split("/") if p not in ("", ".")]
    return base.joinpath(*parts)


def _git(args: list[str], cwd: Path) -> str | None:
    """Best-effort git invocation; ``None`` on any failure (no repo, no git, timeout)."""

    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def _resolve_within_repo(repo_root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``repo_root``; ``None`` unless it names an
    existing regular file that stays within the repo tree.

    The containment check guards against a string like ``"../../secret"``
    (from evidence payloads or ``--include``) escaping the repo and landing
    in a committed corpus snapshot.
    """

    if not rel or "\x00" in rel:
        return None
    try:
        candidate = _posix_join(repo_root, rel)
        resolved = candidate.resolve()
        resolved_root = repo_root.resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(resolved_root):
        return None
    try:
        return resolved if resolved.is_file() else None
    except OSError:
        return None


def _snapshot_failure_reason(repo_root: Path, rel: str) -> str:
    """Distinguish "no such file" from "resolves outside the repo" for
    ``rel`` -- ``_resolve_within_repo`` collapses both to ``None``, which is
    the right thing for a boolean existence check but too vague for a
    user-facing error naming the finding's own (unvalidated-at-collection)
    path, so this re-walks the same resolution steps purely for diagnosis.
    """

    if not rel or "\x00" in rel:
        return "empty or invalid path"
    try:
        candidate = _posix_join(repo_root, rel)
        resolved = candidate.resolve()
        resolved_root = repo_root.resolve()
    except (OSError, ValueError) as exc:
        return f"path could not be resolved ({exc})"
    if not resolved.is_relative_to(resolved_root):
        return f"resolves outside the repo ({resolved})"
    return f"no such file under {repo_root}"


def _walk_strings(value: Any):
    """Yield every string leaf inside a nested dict/list structure."""

    if isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)
    elif isinstance(value, str):
        yield value


def _evidence_paths(finding: dict, repo_root: Path) -> set[str]:
    """Mechanical walk of ``finding["evidence"]`` payloads: string values that
    resolve to an existing repo-relative file. No globbing, no semantic
    filtering of which strings might be "path-shaped" -- existence on disk
    (within the repo) is the only test, matching the brief's "mechanical
    walk... strings only" instruction.
    """

    found: set[str] = set()
    for ev in finding.get("evidence") or []:
        payload = ev.get("payload") if isinstance(ev, dict) else None
        if not isinstance(payload, dict):
            continue
        for s in _walk_strings(payload):
            resolved = _resolve_within_repo(repo_root, _to_posix(s)) if s else None
            if resolved is not None:
                found.add(_to_posix(s))
    return found


def _language_for(path: str, override: str | None) -> str:
    """Resolve case.json's ``language`` field (metadata only)."""

    if override:
        return override
    ext = PurePosixPath(path).suffix.lower()
    if ext in _EXTENSION_LANGUAGES:
        return _EXTENSION_LANGUAGES[ext]
    if ext:
        return ext.lstrip(".")
    return "unknown"


# Producer -> corpus category, derived from audit.py's own registries rather
# than a hand-maintained duplicate: _CLI_FLAG_TO_PRODUCER maps a CLI flag to
# the producer prefix Finding.detector carries; _JUNK_NAME_TO_CLI_FLAG maps
# each JunkAnalyzer's .name (its corpus-category spelling, e.g. "dead_code")
# to that same flag. Chaining producer -> flag -> name gives the category a
# human already sees in --exclude / CLI help, with zero drift risk since both
# tables are read live off audit.py's registries.
_PRODUCER_TO_CLI_FLAG: dict[str, str] = {v: k for k, v in _CLI_FLAG_TO_PRODUCER.items()}
_CLI_FLAG_TO_CATEGORY: dict[str, str] = {v: k for k, v in _JUNK_NAME_TO_CLI_FLAG.items()}

# The CLI-flag registry chain above is a UI naming convention (--exclude flag
# identifiers via JunkAnalyzer.name), not the corpus taxonomy -- it happens to
# already agree with the corpus README's example categories and the legacy
# debris:<category> vocabulary for five of six JunkAnalyzers, but
# DeadPlumbingAnalyzer.name is "dead_plumbing" while the corpus taxonomy (the
# README's own example list, and the legacy debris:plumbing path handled
# below) calls this category "plumbing". The registry chain cannot be
# trusted verbatim as the corpus taxonomy -- override the one confirmed
# collision explicitly rather than silently emitting the wrong directory name.
_CATEGORY_OVERRIDES: dict[str, str] = {
    "dead_plumbing": "plumbing",
}

# Producers outside the JUNK_ANALYZERS registry: Phase 2 (doc analysis),
# Phase 3 (debris), and Phase 3.5 (obligations) are not JunkAnalyzer
# subclasses, so they carry no CLI-flag registry entry.
_SPECIAL_CATEGORY_PRODUCERS: dict[str, str] = {
    "obligations": "obligations",
    "doc": "doc_analysis",
}


def _producer_of(detector: str) -> str:
    """The producer half of a ``"<producer>:<category>"`` detector string."""

    producer, _, _ = (detector or "").partition(":")
    return producer or "uncategorized"


def _category_of(detector: str) -> str:
    """The corpus directory category for a finding's ``detector`` string.

    ``debris:<category>`` findings (Phase 3) already carry the legacy debris
    taxonomy (``dead_code`` / ``dead_params`` / ``plumbing`` / ``latent_bug``)
    as their detector suffix -- the exact category vocabulary the corpus
    README illustrates -- so that suffix is used directly. Every other
    producer routes through the CLI-flag chain above; an unrecognized
    producer falls back to itself so an unknown/future detector never raises.
    """

    producer, _, suffix = (detector or "").partition(":")
    if not producer:
        return "uncategorized"
    if producer == "debris":
        return suffix or "debris"
    if producer in _SPECIAL_CATEGORY_PRODUCERS:
        return _SPECIAL_CATEGORY_PRODUCERS[producer]
    cli_flag = _PRODUCER_TO_CLI_FLAG.get(producer)
    if cli_flag is not None:
        category = _CLI_FLAG_TO_CATEGORY.get(cli_flag, producer)
        return _CATEGORY_OVERRIDES.get(category, category)
    return producer


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.fullmatch(slug or ""):
        raise CorpusEmitError(
            f"invalid --slug {slug!r}: must match [a-z0-9_-]+"
        )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# ledger loading
# ---------------------------------------------------------------------------


def _load_ledger(repo_root: Path) -> dict:
    ledger_path = repo_root / SHADOW_DIR / "analysis" / "decided-findings.json"
    if not ledger_path.exists():
        raise CorpusEmitError(
            f"no decided-findings ledger at {ledger_path} -- run `osoji audit` first"
        )
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusEmitError(f"cannot parse {ledger_path}: {exc}") from exc
    if ledger.get("schema") != DECIDED_FINDINGS_SCHEMA:
        raise CorpusEmitError(
            f"bad {DECIDED_FINDINGS_SCHEMA!r} schema tag "
            f"({ledger.get('schema')!r}) in {ledger_path}"
        )
    return ledger


_MAX_NEAR_MISS_LINES = 20


def _find_finding(ledger: dict, finding_id: str) -> dict:
    """Locate a ledger entry by exact ``id``; a near-miss listing (every
    ledger entry's ``path -> id``, since ids are opaque content hashes with
    no textual "closeness" to fuzzy-match on) on failure.
    """

    findings = ledger.get("findings") or []
    for f in findings:
        if f.get("id") == finding_id:
            return f

    if not findings:
        raise CorpusEmitError(
            f"no finding with id {finding_id!r} -- the decided-findings ledger is empty"
        )

    lines = [f"  {f.get('path')} -> {f.get('id')}" for f in findings]
    shown = lines[:_MAX_NEAR_MISS_LINES]
    if len(lines) > _MAX_NEAR_MISS_LINES:
        shown.append(f"  ... and {len(lines) - _MAX_NEAR_MISS_LINES} more")
    raise CorpusEmitError(
        f"no finding with id {finding_id!r} in the decided-findings ledger.\n"
        "Findings in this ledger (path -> id):\n" + "\n".join(shown)
    )


def _resolve_expected_verdict(finding: dict, override: str | None) -> str:
    if override is not None:
        if override not in ("confirmed", "dismissed"):
            raise CorpusEmitError(
                f"--expected-verdict must be 'confirmed' or 'dismissed', got {override!r}"
            )
        return override
    decided = finding.get("verdict")
    if decided in ("confirmed", "dismissed"):
        return decided
    raise CorpusEmitError(
        f"finding {finding.get('id')!r} has verdict {decided!r} (uncertain/undecided) "
        "-- pass --expected-verdict confirmed|dismissed to seed ground truth"
    )


# ---------------------------------------------------------------------------
# dest resolution (CLI-facing)
# ---------------------------------------------------------------------------


def resolve_dest(repo_root: Path, dest_override: Path | None) -> Path:
    """Resolve the corpus holding directory for ``osoji corpus emit``.

    Precedence: an explicit ``--dest``, then ``$OSOJI_CORPUS_DEST``, then
    ``<repo_root>/tests/fixtures/prompt_regression/_holding`` when that
    corpus directory exists. Raises :class:`CorpusEmitError` naming both
    fallback options otherwise.
    """

    if dest_override is not None:
        return Path(dest_override)

    env_value = os.environ.get(ENV_CORPUS_DEST)
    if env_value:
        return Path(env_value)

    default_corpus = repo_root / "tests" / "fixtures" / "prompt_regression"
    if default_corpus.is_dir():
        return default_corpus / "_holding"

    raise CorpusEmitError(
        "cannot resolve a corpus destination: pass --dest, set "
        f"${ENV_CORPUS_DEST}, or run from a repo whose "
        "tests/fixtures/prompt_regression/ directory exists (the osoji corpus)"
    )


# ---------------------------------------------------------------------------
# emit_case
# ---------------------------------------------------------------------------


def emit_case(
    repo_root: Path,
    finding_id: str,
    slug: str,
    dest: Path,
    *,
    expected_verdict: str | None = None,
    reasoning: str | None = None,
    gray: bool = False,
    include: Sequence[str] = (),
    language: str | None = None,
) -> Path:
    """Snapshot one decided finding into a ``corpus-case/1`` stub under ``dest``.

    Reads ``<repo_root>/.osoji/analysis/decided-findings.json``, locates the
    finding named by ``finding_id``, and writes ``<dest>/<category>/case_<slug>/``
    (``case.json`` + ``finding.json`` + ``expected.json`` + ``source/`` + any
    ``symbols/``/``facts/``/``shadow/`` sidecars) matching the corpus-case/1
    layout documented in ``tests/fixtures/prompt_regression/README.md``.

    Every input is validated before any file is written -- a rejected slug,
    missing finding, oversized file set, missing ``--include`` file, or an
    undecided verdict without ``--expected-verdict`` all raise
    :class:`CorpusEmitError` before the destination directory is even
    checked, so a failed call never leaves a half-written case behind.
    """

    _validate_slug(slug)
    repo_root = Path(repo_root)
    dest = Path(dest)

    ledger = _load_ledger(repo_root)
    finding = _find_finding(ledger, finding_id)

    finding_path = _to_posix(finding.get("path", ""))
    relevant: set[str] = {finding_path} if finding_path else set()
    relevant |= _evidence_paths(finding, repo_root)

    for raw in include:
        rel = _to_posix(raw)
        if _resolve_within_repo(repo_root, rel) is None:
            raise CorpusEmitError(f"--include file does not exist: {raw}")
        relevant.add(rel)

    if len(relevant) > MAX_FILES:
        # --include is additive-only (it can only grow `relevant`, never
        # narrow it), so it is never a fix here -- the finding's own evidence
        # already references too many files for a self-contained case. There
        # is currently no knob to narrow that automatically; the options are
        # to emit a different (more targeted) finding, or extend this tool.
        raise CorpusEmitError(
            f"{len(relevant)} files exceeds the corpus-emit cap of {MAX_FILES} "
            "(snapshot-bloat guard): the finding's evidence references too "
            "many files for a self-contained case. Emit a different finding "
            "with more targeted evidence, or extend corpus_emit.py to support "
            "narrowing the selection."
        )

    resolved_verdict = _resolve_expected_verdict(finding, expected_verdict)
    resolved_reasoning = (
        reasoning if reasoning is not None else (finding.get("triage_reasoning") or "")
    )
    resolved_language = _language_for(finding_path, language)
    category = _category_of(finding.get("detector", ""))
    producer = _producer_of(finding.get("detector", ""))

    case_dir = dest / category / f"case_{slug}"
    if case_dir.exists():
        raise CorpusEmitError(f"case directory already exists: {case_dir}")

    now_iso = datetime.now(timezone.utc).isoformat()

    # -- filesystem writes from here on -------------------------------
    source_root = case_dir / "source"
    for rel in sorted(relevant):
        # Re-resolved (not just re-checked) here, including for the finding's
        # own path, which -- unlike evidence/--include paths -- is included
        # in `relevant` unconditionally at collection time (deliverable 2,
        # point 2): this is where a missing or repo-escaping finding.path
        # finally gets a clear error instead of a silent skip.
        src = _resolve_within_repo(repo_root, rel)
        if src is None:
            raise CorpusEmitError(
                f"cannot snapshot {rel!r}: {_snapshot_failure_reason(repo_root, rel)}"
            )
        dest_file = _posix_join(source_root, rel)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_file)

        for subdir, suffix in _SIDECARS:
            sidecar_rel = f"{SHADOW_DIR}/{subdir}/{rel}{suffix}"
            sidecar_src = _posix_join(repo_root, sidecar_rel)
            if sidecar_src.is_file():
                sidecar_dest = _posix_join(case_dir, f"{subdir}/{rel}{suffix}")
                sidecar_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sidecar_src, sidecar_dest)

    finding_out = dict(finding)
    finding_out["path"] = finding_path
    for key in (
        "verdict", "confidence", "triage_reasoning", "suggested_fix",
        "severity", "contract_class", "evidence_fingerprint",
    ):
        finding_out[key] = None
    finding_out["evidence"] = []

    _write_json(case_dir / "case.json", {
        "schema": CORPUS_CASE_SCHEMA,
        "slug": slug,
        "category": category,
        "detector": producer,
        "gap_type": finding.get("gap_type"),
        "language": resolved_language,
        "origin": {
            "repo": repo_root.name,
            "remote": _git(["remote", "get-url", "origin"], repo_root),
            "commit": _git(["rev-parse", "HEAD"], repo_root) or "unknown",
            "swept_at": now_iso,
            "osoji_version": __version__,
            "sweep_run": None,
        },
        "snapshot_ref": None,
        "evidence_policy": "rebuild",
    })
    _write_json(case_dir / "finding.json", finding_out)
    _write_json(case_dir / "expected.json", {
        "schema": CORPUS_EXPECTED_SCHEMA,
        "verdict": resolved_verdict,
        "reasoning": resolved_reasoning,
        "gray": bool(gray),
        "gray_reason": None,
        "expected_contract_class": None,
        "adjudicated_by": "sweep-proposed",
        "adjudicated_at": now_iso,
        "accepted": False,
    })

    return case_dir
