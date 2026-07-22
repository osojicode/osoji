"""Zero-LLM closure diff — did the fixes actually close the findings?

``osoji verify`` (Track 2 PR-D, osojicode/work#35) answers a single question
without any model call: given a *baseline* audit result and the *current* one,
which prior findings closed, which are still open, and which are new. The sweep
workflow snapshots a baseline before fixing, then verifies closure after.

Inputs are two ``audit-result.json`` files as produced by
:func:`osoji.audit.format_audit_json` — a ``{"issues": [...]}`` object where
each issue carries ``path``/``severity``/``category``/``message`` and, when a
decided Finding backed it, an optional ``finding_id``/``verdict``.

**Join model.** Findings are matched across the two sides in two passes:

1. by ``finding_id`` when *both* sides carry equal ids, then
2. by a composite key for whatever remains unmatched.

The composite key is ``(path, category, message-core)`` and deliberately holds
**no line numbers**. :func:`osoji.findings.compute_finding_id` folds line
numbers into the id of a *symbol-less* finding, so inserting a line above such a
finding changes its id between runs; without a line-agnostic fallback every
reflow would masquerade as (closed + new). The message-core strips osoji's own
``L<n>[-<n>]:`` location marker (and any ``[AST]`` prefix) from the message,
which is emitted by osoji itself and is therefore language-agnostic.

**Dismissals.** Empirically the audit pipeline *drops* dismissed findings from
``audit-result.json`` entirely — debris via ``suppressed_indices``, obligations
via an explicit ``continue``, and the junk analyzers keep confirmed findings
only (see ``audit.py`` phase 3 / 3.5 and the ``junk_*`` analyzers). So a
dismissal is, today, indistinguishable from a code fix and lands in ``closed``.
The ``closed_by_dismissal`` bucket is retained in the contract and populated via
the one mechanically-observable route — a matched *current* finding that still
carries ``verdict == "dismissed"`` — which keeps the diff correct should a
future pipeline choose to retain dismissed findings with their verdict marker.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "closure-diff/1"

# osoji's own message location marker, e.g. "L42: ", "L10-15: ", "[AST] L7: ".
# It is prepended by the audit serializer, not by any language's tooling, so
# stripping it stays language-agnostic. Line numbers must never enter a join
# key (see module docstring).
_LOCATION_MARKER = re.compile(r"^(?:\[AST\]\s*)?L\d+(?:-\d+)?:\s*")


def message_core(message: str) -> str:
    """Return the reflow-stable core of an issue message.

    Strips a leading ``[AST]`` marker and osoji's ``L<n>[-<n>]:`` location
    prefix so that the same finding at a different line collapses to one key.
    """

    return _LOCATION_MARKER.sub("", message or "").strip()


@dataclass(frozen=True)
class ClosureRecord:
    """One finding as reported in a closure bucket."""

    path: str
    category: str
    severity: str | None
    finding_id: str | None
    join_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "category": self.category,
            "severity": self.severity,
            "finding_id": self.finding_id,
            "join_key": self.join_key,
        }


@dataclass
class _Issue:
    """Working view over one serialized audit issue."""

    raw: dict
    path: str
    category: str
    severity: str | None
    finding_id: str | None
    verdict: str | None
    composite: tuple[str, str, str]

    @property
    def composite_key(self) -> str:
        return " | ".join(self.composite)

    @property
    def preferred_key(self) -> str:
        """The key under which an *unmatched* finding is reported."""

        return self.finding_id or self.composite_key

    def record(self, join_key: str) -> ClosureRecord:
        return ClosureRecord(
            path=self.path,
            category=self.category,
            severity=self.severity,
            finding_id=self.finding_id,
            join_key=join_key,
        )


def _as_issue(raw: dict) -> _Issue:
    path = str(raw.get("path", ""))
    category = str(raw.get("category", ""))
    fid = raw.get("finding_id")
    return _Issue(
        raw=raw,
        path=path,
        category=category,
        severity=raw.get("severity"),
        finding_id=fid if fid else None,
        verdict=raw.get("verdict"),
        composite=(path, category, message_core(raw.get("message", ""))),
    )


@dataclass
class ClosureDiff:
    """The four closure buckets. Bucket names are part of the ``closure-diff/1``
    contract and must not be renamed."""

    closed: list[ClosureRecord] = field(default_factory=list)
    closed_by_dismissal: list[ClosureRecord] = field(default_factory=list)
    still_open: list[ClosureRecord] = field(default_factory=list)
    new: list[ClosureRecord] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Nonzero while any finding is still open — the whole point of verify."""

        return 1 if self.still_open else 0

    @property
    def counts(self) -> dict[str, int]:
        return {
            "closed": len(self.closed),
            "closed_by_dismissal": len(self.closed_by_dismissal),
            "still_open": len(self.still_open),
            "new": len(self.new),
        }


def compute_closure(
    baseline_issues: list[dict], current_issues: list[dict]
) -> ClosureDiff:
    """Diff baseline findings against current ones into the four buckets."""

    base = [_as_issue(i) for i in baseline_issues]
    cur = [_as_issue(i) for i in current_issues]

    matched_base: set[int] = set()
    matched_cur: set[int] = set()
    # (base_issue, cur_issue, join_key) for every matched pair
    pairs: list[tuple[_Issue, _Issue, str]] = []

    # Pass 1: join by finding_id where both sides carry the same non-null id.
    cur_by_id: dict[str, list[int]] = {}
    for j, c in enumerate(cur):
        if c.finding_id:
            cur_by_id.setdefault(c.finding_id, []).append(j)
    for i, b in enumerate(base):
        if not b.finding_id:
            continue
        for j in cur_by_id.get(b.finding_id, []):
            if j not in matched_cur:
                matched_base.add(i)
                matched_cur.add(j)
                pairs.append((b, cur[j], b.finding_id))
                break

    # Pass 2: join whatever is left by composite key (line-number agnostic).
    cur_by_comp: dict[str, list[int]] = {}
    for j, c in enumerate(cur):
        if j in matched_cur:
            continue
        cur_by_comp.setdefault(c.composite_key, []).append(j)
    for i, b in enumerate(base):
        if i in matched_base:
            continue
        for j in cur_by_comp.get(b.composite_key, []):
            if j not in matched_cur:
                matched_base.add(i)
                matched_cur.add(j)
                pairs.append((b, cur[j], b.composite_key))
                break

    diff = ClosureDiff()

    # Baseline findings with no current match closed (fixed, or silently
    # dismissed — the two are indistinguishable; see module docstring).
    for i, b in enumerate(base):
        if i not in matched_base:
            diff.closed.append(b.record(b.preferred_key))

    # Matched pairs: a current dismissal is closed-by-dismissal, else still open.
    for b, c, key in pairs:
        if c.verdict == "dismissed":
            diff.closed_by_dismissal.append(c.record(key))
        else:
            diff.still_open.append(c.record(key))

    # Current findings with no baseline match are new.
    for j, c in enumerate(cur):
        if j not in matched_cur:
            diff.new.append(c.record(c.preferred_key))

    return diff


def closure_to_dict(diff: ClosureDiff) -> dict[str, Any]:
    """Render the diff as the ``closure-diff/1`` machine shape."""

    return {
        "schema": SCHEMA,
        "counts": diff.counts,
        "closed": [r.to_dict() for r in diff.closed],
        "closed_by_dismissal": [r.to_dict() for r in diff.closed_by_dismissal],
        "still_open": [r.to_dict() for r in diff.still_open],
        "new": [r.to_dict() for r in diff.new],
    }


def load_issues(path: Path) -> list[dict]:
    """Read the ``issues`` array from a serialized audit-result.json."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    issues = data.get("issues", [])
    return [i for i in issues if isinstance(i, dict)]


def format_table(diff: ClosureDiff) -> str:
    """Render a human-readable summary table + per-bucket finding lines."""

    counts = diff.counts
    lines = [
        "Closure diff (baseline vs current):",
        f"  closed .............. {counts['closed']}",
        f"  closed_by_dismissal . {counts['closed_by_dismissal']}",
        f"  still_open .......... {counts['still_open']}",
        f"  new ................. {counts['new']}",
    ]

    def _section(title: str, records: list[ClosureRecord]) -> None:
        if not records:
            return
        lines.append("")
        lines.append(f"{title}:")
        for r in records:
            sev = r.severity or "-"
            lines.append(f"  [{sev}] {r.path} ({r.category})")

    _section("Still open", diff.still_open)
    _section("New", diff.new)
    _section("Closed", diff.closed)
    _section("Closed by dismissal", diff.closed_by_dismissal)

    lines.append("")
    if diff.still_open:
        lines.append(f"{counts['still_open']} finding(s) still open.")
    else:
        lines.append("All baseline findings closed.")

    return "\n".join(lines)
