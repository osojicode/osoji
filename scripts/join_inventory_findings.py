"""Join a #643-style hunk inventory with an osoji audit result for adjudication.

Usage:
    python scripts/join_inventory_findings.py --inventory <rows.jsonl> \
        --audit <audit-result.json> --repo <path> --base <sha> --head <sha> \
        --out <dir>

For every inventory row (one claim group in the comparator diff) collect the
osoji findings on the same (old-side) path, flag phrase overlap between each
finding's quoted phrases and the row's claim text or the removed diff lines,
and write:
  - rows.json     : rows with their candidate findings (input for adjudication)
  - findings.json : findings with the rows on their path
  - summary.json  : counts per partition/domain and mechanical-overlap tallies
Adjudication (hit / miss / partial) is done by a reader, not here.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

PHRASE_RE = re.compile(r"[`'\"“‘]([^`'\"”’\n]{3,100})[`'\"”’]")


def norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def phrases_of(text: str) -> list[str]:
    seen: list[str] = []
    for m in PHRASE_RE.finditer(text or ""):
        p = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        specific = len(p) >= 8 or " " in p or any(ch in p for ch in "/_:.()-@")
        if len(p) >= 4 and specific and p not in seen:
            seen.append(p)
    return seen


def removed_text_by_hunk(repo: Path, base: str, head: str) -> dict[tuple[str, int], str]:
    """Map (old_path, old_start) -> lowercased removed text of that hunk."""
    out = subprocess.run(
        ["git", "diff", "-M", "--unified=0", f"{base}..{head}"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout
    result: dict[tuple[str, int], str] = {}
    old_path = None
    seq = 0
    buf: list[str] = []
    key = None

    def flush() -> None:
        if key is not None:
            result[key] = re.sub(r"\s+", " ", "\n".join(buf)).lower()

    for line in out.splitlines():
        if line.startswith("diff --git"):
            flush(); key = None; buf = []; old_path = None
        elif line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else norm(line[6:])
        elif line.startswith("+++ "):
            if old_path is None:
                old_path = norm(line[6:])
        elif line.startswith("@@"):
            flush(); seq += 1
            m = re.match(r"^@@ -(\d+)", line)
            key = (old_path or "?", int(m.group(1)) if m else seq); buf = []
        elif key is not None and line.startswith("-"):
            buf.append(line[1:].strip())
    flush()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True, type=Path)
    ap.add_argument("--audit", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    rows = [json.loads(l) for l in args.inventory.read_text(encoding="utf-8").splitlines() if l.strip()]
    data = json.loads(args.audit.read_text(encoding="utf-8"))
    findings = data.get("issues") if isinstance(data, dict) else data
    removed = removed_text_by_hunk(args.repo, args.base, args.head)

    by_path: dict[str, list[dict]] = defaultdict(list)
    for i, f in enumerate(findings):
        fid = f.get("finding_id") or f"issue{i:04d}"
        f = {**f, "_id": fid, "_path": norm(str(f.get("path", ""))),
             "_phrases": phrases_of(f.get("message") or "")}
        by_path[f["_path"]].append(f)

    # Removed text is keyed by (old path, old_start); rows carry old_starts per merged hunk.
    out_rows = []
    rows_by_path: dict[str, list[str]] = defaultdict(list)
    for r_i, r in enumerate(rows):
        rid = f"r{r_i + 1:03d}"
        path = norm(r["path"])
        rows_by_path[path].append(rid)
        starts = r.get("old_starts") or [r.get("old_start")]
        old_text = " ".join(removed.get((path, int(s)), "") for s in starts if s is not None)
        claim_l = (r.get("claim") or "").lower()
        cands = []
        for f in by_path.get(path, []):
            overlap = [p for p in f["_phrases"] if p in old_text or p in claim_l]
            cands.append({
                "finding_id": f["_id"], "category": f.get("category"),
                "severity": f.get("severity"), "verdict": f.get("verdict"),
                "confidence": f.get("confidence"),
                "phrase_overlap": overlap,
                "message": (f.get("message") or "")[:600],
            })
        cands.sort(key=lambda c: (-len(c["phrase_overlap"]), c["finding_id"]))
        out_rows.append({
            "row_id": rid, **{k: r.get(k) for k in ("path", "renamed_to", "partition", "domain", "kind",
                                                   "old_start", "old_len", "hunk_count", "claim",
                                                   "evidence_path", "notes")},
            "removed_text": old_text[:800],
            "candidates": cands,
            "mechanical": "phrase" if any(c["phrase_overlap"] for c in cands) else ("file" if cands else "none"),
            "adjudication": None, "matched_finding_id": None, "adjudication_note": None,
        })

    out_findings = []
    for path, fs in by_path.items():
        for f in fs:
            out_findings.append({
                "finding_id": f["_id"], "path": path, "category": f.get("category"),
                "severity": f.get("severity"), "verdict": f.get("verdict"),
                "confidence": f.get("confidence"), "line_start": f.get("line_start"),
                "line_end": f.get("line_end"), "message": f.get("message"),
                "remediation": f.get("remediation"), "triage_reasoning": f.get("triage_reasoning"),
                "suggested_fix": f.get("suggested_fix"),
                "rows_on_path": rows_by_path.get(path, []),
                "in_diff": bool(rows_by_path.get(path)),
            })

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rows.json").write_text(json.dumps(out_rows, indent=1), encoding="utf-8")
    (args.out / "findings.json").write_text(json.dumps(out_findings, indent=1), encoding="utf-8")
    cc = [r for r in out_rows if r["partition"] in ("correction", "deletion") and r["domain"] == "checkout"]
    summary = {
        "rows_total": len(out_rows),
        "rows_by_partition": dict(Counter(r["partition"] for r in out_rows)),
        "checkout_corrections": len(cc),
        "checkout_corrections_mechanical": dict(Counter(r["mechanical"] for r in cc)),
        "findings_total": len(out_findings),
        "findings_by_category": dict(Counter(f["category"] for f in out_findings)),
        "findings_in_diff_files": sum(1 for f in out_findings if f["in_diff"]),
        "findings_outside_diff": sum(1 for f in out_findings if not f["in_diff"]),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
