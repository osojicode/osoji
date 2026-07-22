"""Incremental-audit verdict manifest (V1-9).

``.osoji/audit-manifest.json`` persists Triage verdicts keyed by finding id so
a later ``osoji audit --incremental`` run can reuse them for findings whose
evidence fingerprint is unchanged (see concepts/incremental-audit.md in the
project wiki). The fingerprint already embeds the Claim Builder schema version
and osoji's ``impl_hash`` (:func:`~osoji.claim_builder.compute_evidence_fingerprint`),
so a logic change invalidates every entry by construction; the manifest-level
``osoji_version`` stamp is a coarse fast-path check on top.

Duplicate finding ids (possible for symbol-less findings) collapse to one
entry, last write wins — harmless, because a reuse still requires the exact
evidence fingerprint to match.

The manifest lives directly under ``.osoji/`` (like ``staleness.json``), NOT
under ``.osoji/analysis/``, which the audit wipes at the start of every run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .claim_builder import CLAIM_BUILDER_SCHEMA_VERSION
from .findings import Finding
from .hasher import compute_impl_hash

#: Manifest file format version; bump on breaking shape changes.
MANIFEST_SCHEMA = 1


class IncrementalAuditError(RuntimeError):
    """Raised when an incremental-audit precondition fails (e.g. bad --since)."""


def current_version(project_rules: str | None = None) -> str:
    """Return the osoji logic version stamp for manifest validation.

    ``project_rules`` (maintainer-declared triage intent, work#35) folds into the
    stamp so cached verdicts invalidate when the rules change: the rules ride in
    the Triage user message, so a rules edit is a logic change for cache
    purposes. Absent or blank rules leave the stamp byte-identical to the
    pre-rules version — existing manifests stay valid (no invalidation for
    users who declare none).
    """

    base = f"{CLAIM_BUILDER_SCHEMA_VERSION}:{compute_impl_hash()}"
    if not (project_rules and project_rules.strip()):
        return base
    digest = hashlib.sha256(project_rules.encode("utf-8")).hexdigest()[:16]
    return f"{base}:rules-{digest}"


def get_head_commit(root: Path) -> str | None:
    """Return the current git HEAD SHA for ``root``, or None outside a repo."""

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def load_manifest(path: Path) -> dict | None:
    """Load and validate a manifest; None on missing/corrupt/unknown shape."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != MANIFEST_SCHEMA:
        return None
    if not isinstance(data.get("verdicts"), dict):
        return None
    return data


def write_manifest(
    path: Path,
    verdicts: dict[str, dict],
    *,
    commit: str | None,
    version: str,
) -> None:
    """Write the manifest atomically (temp file + rename)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "audited_commit": commit,
        "osoji_version": version,
        "verdicts": verdicts,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def cache_from_verdicts(verdicts: dict[str, dict]) -> dict[tuple[str, str], dict]:
    """Build the ``(finding.id, fingerprint) -> entry`` cache Triage consumes.

    Entries without a fingerprint are cache-ineligible (decision 0014) and
    are skipped.
    """

    return {
        (fid, entry["evidence_fingerprint"]): entry
        for fid, entry in verdicts.items()
        if isinstance(entry, dict) and entry.get("evidence_fingerprint")
    }


def _producer(detector: str) -> str:
    """Return the producer prefix of a detector tag (``deadcode:dead_symbol``)."""

    return detector.split(":", 1)[0]


def merge_verdicts(
    previous: dict[str, dict],
    harvested: dict[str, dict],
    ran_producers: set[str],
) -> dict[str, dict]:
    """Merge harvested verdicts over a previous manifest, producer-scoped.

    Entries from producers that ran this audit are replaced wholesale (so
    findings that disappeared are dropped); entries from producers that did
    not run (e.g. a plain run after a ``--full`` one) are preserved.
    """

    merged = {
        fid: entry
        for fid, entry in previous.items()
        if isinstance(entry, dict)
        and _producer(str(entry.get("detector", ""))) not in ran_producers
    }
    merged.update(harvested)
    return merged


@dataclass
class VerdictSession:
    """Per-audit-run verdict cache state, threaded through the Triage seams.

    ``cache`` is consulted by :meth:`Triage.decide_batch`; ``harvest`` records
    decided findings for the manifest rewrite and counts cache hits with the
    same ``(id, fingerprint)`` rule the cache lookup uses.
    """

    cache: dict[tuple[str, str], dict] = field(default_factory=dict)
    harvested: dict[str, dict] = field(default_factory=dict)
    claims_seen: int = 0
    cache_hits: int = 0

    def harvest(self, findings: Iterable[Finding]) -> None:
        for finding in findings:
            self.claims_seen += 1
            fingerprint = finding.evidence_fingerprint
            if fingerprint is not None and (finding.id, fingerprint) in self.cache:
                self.cache_hits += 1
            if finding.verdict is None or fingerprint is None:
                continue
            self.harvested[finding.id] = {
                "detector": finding.detector,
                "evidence_fingerprint": fingerprint,
                "verdict": finding.verdict,
                "confidence": finding.confidence,
                "triage_reasoning": finding.triage_reasoning,
                "suggested_fix": finding.suggested_fix,
                "severity": finding.severity,
                "contract_class": finding.contract_class,
                # LLM-assigned split for parked claims (decisions/0025);
                # _apply_cached re-applies it under the same only-if-parked guard.
                "gap_type": finding.gap_type,
            }

    @property
    def hit_rate(self) -> float | None:
        if self.claims_seen == 0:
            return None
        return self.cache_hits / self.claims_seen
