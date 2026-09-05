"""Score osoji findings against labeled benchmark rows (wiki specs/0005).

Rows are the docs-fix ground truth at a parent commit (``bench.mine`` +
``bench.label``); findings are what osoji reported at that parent, keyed by
parent sha. A row counts when its label is a checkout-domain correction or
deletion. A row is *hit* when a finding on the same document overlaps its
old-side line range within ``window`` lines, or quotes a phrase that occurs
in the removed text. Findings that hit no row are precision candidates for
a reader panel; they are counted here, never judged.

Usage:
    python scripts/bench/score.py --rows bench/<repo>/rows.labeled.jsonl \
        --findings-dir bench/<repo>/runs/<run>/ [--reader r1] [--window 5] [--run-parents-only]

``--findings-dir`` holds one ``<parent-sha>.json`` per run parent, each an
osoji audit result (``{"issues": [...]}``) or a bare list of issues.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

COUNTING_PARTITIONS = frozenset({"correction", "deletion"})
COUNTING_DOMAIN = "checkout"
_PHRASE_RE = re.compile(r"[`'\"“‘]([^`'\"”’\n]{3,100})[`'\"”’]")


def norm_path(path: str) -> str:
    path = str(path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def label_of(row: dict, reader: str | None) -> dict | None:
    """The row's label from ``reader``, or its only label when reader is None."""

    labels = row.get("labels") or {}
    if not labels:
        return None
    if reader is not None:
        return labels.get(reader)
    return next(iter(labels.values()))


def counting_rows(rows: list[dict], reader: str | None) -> list[dict]:
    kept = []
    for row in rows:
        label = label_of(row, reader)
        if label and label.get("partition") in COUNTING_PARTITIONS and label.get("domain") == COUNTING_DOMAIN:
            kept.append(row)
    return kept


def _phrases(text: str) -> list[str]:
    seen: list[str] = []
    for m in _PHRASE_RE.finditer(text or ""):
        p = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        specific = len(p) >= 8 or " " in p or any(ch in p for ch in "/_:.()-@")
        if len(p) >= 4 and specific and p not in seen:
            seen.append(p)
    return seen


def match_findings(row: dict, findings: list[dict], window: int = 5) -> list[dict]:
    """Findings on the row's document that overlap its lines or quote its removed text."""

    path = norm_path(row["path"])
    lo = int(row["old_start"]) - window
    hi = int(row["old_start"]) + max(int(row.get("old_len") or 1), 1) - 1 + window
    removed = re.sub(r"\s+", " ", " ".join(row.get("minus_text") or [])).lower()
    hits: list[dict] = []
    for f in findings:
        if norm_path(f.get("path", "")) != path:
            continue
        start = f.get("line_start")
        end = f.get("line_end") or start
        if start is not None and not (int(end) < lo or int(start) > hi):
            hits.append(f)
            continue
        if any(p in removed for p in _phrases(f.get("message") or "")):
            hits.append(f)
    return hits


def score(
    rows: list[dict], findings_by_parent: dict[str, list[dict]], *,
    reader: str | None = None, window: int = 5, run_parents_only: bool = False,
    parent_override: dict[str, str] | None = None,
) -> dict:
    """Recall over counting rows, overall and by kind / claim shape.

    ``parent_override`` maps row_id → the sha the row was actually evaluated
    at (fixed-snapshot runs, ``bench.run.snapshot_plan``).
    """

    override = parent_override or {}
    counted = [
        {**r, "parent": override.get(r["row_id"], r["parent"])} for r in counting_rows(rows, reader)
    ]
    parents_total = {r["parent"] for r in counted}
    if run_parents_only:
        counted = [r for r in counted if r["parent"] in findings_by_parent]
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "hits": 0})
    by_shape: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "hits": 0})
    detail = []
    matched_ids: set[tuple[str, int]] = set()
    candidate_ids: set[tuple[str, int]] = set()
    hits = 0
    rows_with_candidates = 0
    for row in counted:
        label = label_of(row, reader) or {}
        findings = findings_by_parent.get(row["parent"], [])
        matches = match_findings(row, findings, window=window)
        # Same-document findings that neither overlap the lines nor quote the
        # removed text: not a hit, not noise — the shipping doc checker emits
        # no line numbers, so these need reader adjudication (the honesty
        # test's "candidate_hit_file_level" bucket).
        row_path = norm_path(row["path"])
        candidates = [f for f in findings
                      if norm_path(f.get("path", "")) == row_path and not any(f is m for m in matches)]
        hit = bool(matches)
        hits += hit
        rows_with_candidates += bool(candidates)
        by_kind[label.get("kind", "other")]["rows"] += 1
        by_shape[label.get("claim_shape", "other")]["rows"] += 1
        if hit:
            by_kind[label.get("kind", "other")]["hits"] += 1
            by_shape[label.get("claim_shape", "other")]["hits"] += 1
            for m in matches:
                matched_ids.add((row["parent"], id(m)))
        for c in candidates:
            candidate_ids.add((row["parent"], id(c)))
        detail.append({
            "row_id": row["row_id"], "parent": row["parent"], "path": row["path"],
            "old_start": row["old_start"], "kind": label.get("kind"), "claim_shape": label.get("claim_shape"),
            "hit": hit, "matched": [m.get("message", "")[:160] for m in matches],
            "candidates": [c.get("message", "")[:160] for c in candidates],
        })
    candidate_ids -= matched_ids
    findings_total = sum(len(v) for v in findings_by_parent.values())
    unmatched = sum(
        1 for parent, fs in findings_by_parent.items() for f in fs
        if (parent, id(f)) not in matched_ids and (parent, id(f)) not in candidate_ids
    )
    return {
        "rows": len(counted), "hits": hits,
        "recall": (hits / len(counted)) if counted else None,
        "rows_with_candidates": rows_with_candidates,
        "by_kind": dict(by_kind), "by_shape": dict(by_shape),
        "parents_total": len(parents_total), "parents_run": len(parents_total & set(findings_by_parent)),
        "findings_total": findings_total, "findings_candidate": len(candidate_ids),
        "findings_unmatched": unmatched,
        "rows_detail": detail,
    }


def _load_findings_dir(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for file in sorted(path.glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        issues = data.get("issues") if isinstance(data, dict) else data
        out[file.stem] = [i for i in (issues or []) if i.get("exclude_key") in (None, "doc-analysis", "doc-claims")]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--findings-dir", required=True, type=Path)
    ap.add_argument("--reader", default=None)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--run-parents-only", action="store_true")
    ap.add_argument("--snapshot-rows", type=Path, default=None,
                    help="snapshot-rows.json written by run.py --snapshot (row_id → sha)")
    ap.add_argument("--out", type=Path, default=None, help="write the full result (with rows_detail) here")
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.rows.read_text(encoding="utf-8").splitlines() if l.strip()]
    findings = _load_findings_dir(args.findings_dir)
    override = json.loads(args.snapshot_rows.read_text(encoding="utf-8")) if args.snapshot_rows else None
    result = score(rows, findings, reader=args.reader, window=args.window,
                   run_parents_only=args.run_parents_only, parent_override=override)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "rows_detail"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
