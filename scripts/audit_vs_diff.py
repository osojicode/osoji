"""Score an osoji audit result against a git diff.

Usage:
    python scripts/audit_vs_diff.py --audit <audit-result.json> --repo <path> \
        --base <sha> --head <sha> [--window 5] [--exclude GLOB ...] --out <dir>

For every finding in the audit result, decide whether the diff BASE..HEAD
touched it: a hunk whose old-side (-a,b) range lies within --window lines of
the finding's [line_start, line_end] is a candidate hit. Findings on files the
diff never touched are "osoji_only" by construction. Hunks with no nearby
finding are "diff_only". File-level findings (no line) match on path alone.

Writes findings.csv, hunks.csv and summary.json into --out. Adjudication of
the candidate hits and the diff_only hunks is a separate, human/LLM step.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
# Quoted or backticked phrases inside a finding message: the false claim it names.
PHRASE_RE = re.compile(r"[`'\"“‘]([^`'\"”’\n]{3,100})[`'\"”’]")


def phrases_of(message: str) -> list[str]:
    seen: list[str] = []
    for m in PHRASE_RE.finditer(message or ""):
        p = re.sub(r"\s+", " ", m.group(1)).strip().lower()
        # Drop generic single tokens ('class', 'build', 'python'): keep phrases
        # that are long, multi-word, or look like paths/identifiers/commands.
        specific = len(p) >= 8 or " " in p or any(ch in p for ch in "/_:.()-@")
        if len(p) >= 4 and specific and p not in seen:
            seen.append(p)
    return seen


def norm(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def parse_diff(repo: Path, base: str, head: str) -> tuple[list[dict], dict[str, str]]:
    """Return (hunks, renames) with old-side line ranges. renames maps old->new path."""
    out = subprocess.run(
        ["git", "diff", "-M", "--unified=0", f"{base}..{head}"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True,
    ).stdout
    hunks: list[dict] = []
    renames: dict[str, str] = {}
    old_path = new_path = None
    removed: list[str] = []
    added: list[str] = []
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur, removed, added
        if cur is not None:
            cur["removed_sample"] = " | ".join(removed[:3])[:240]
            cur["added_sample"] = " | ".join(added[:3])[:240]
            cur["removed_lines"] = len(removed)
            cur["added_lines"] = len(added)
            cur["_removed_full"] = re.sub(r"\s+", " ", "\n".join(removed)).lower()
            hunks.append(cur)
        cur, removed, added = None, [], []

    for line in out.splitlines():
        if line.startswith("diff --git"):
            flush()
            old_path = new_path = None
        elif line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else norm(line[6:])
        elif line.startswith("+++ "):
            new_path = None if line[4:] == "/dev/null" else norm(line[6:])
            if old_path and new_path and old_path != new_path:
                renames[old_path] = new_path
        elif line.startswith("@@"):
            flush()
            m = HUNK_RE.match(line)
            if not m:
                continue
            a, b, c, d = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
            old_len = 1 if b is None else int(b)
            new_len = 1 if d is None else int(d)
            path = old_path or new_path or "?"
            cur = {
                "hunk_id": f"h{len(hunks) + 1:04d}",
                "old_path": old_path or "",
                "new_path": new_path or "",
                "path": path,
                "old_start": a,
                "old_end": a + max(old_len, 1) - 1,
                "old_len": old_len,
                "new_start": c,
                "new_len": new_len,
                "kind": "new_file" if old_path is None else ("deleted_file" if new_path is None else "edit"),
            }
        elif cur is not None:
            if line.startswith("-"):
                removed.append(line[1:].strip())
            elif line.startswith("+"):
                added.append(line[1:].strip())
    flush()
    return hunks, renames


def load_findings(audit_path: Path) -> list[dict]:
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    issues = data.get("issues") if isinstance(data, dict) else data
    if issues is None:
        raise SystemExit("audit json has no 'issues' list")
    return issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--exclude", action="append", default=[],
                    help="glob of diff paths to drop from the denominator (generated/derived files)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    hunks, renames = parse_diff(args.repo, args.base, args.head)
    excluded = [h for h in hunks if any(fnmatch.fnmatch(h["path"], g) for g in args.exclude)]
    hunks = [h for h in hunks if h not in excluded]
    by_path: dict[str, list[dict]] = defaultdict(list)
    for h in hunks:
        by_path[h["path"]].append(h)

    findings = load_findings(args.audit)
    f_rows = []
    matched_by_hunk: dict[str, list[str]] = defaultdict(list)
    for i, f in enumerate(findings):
        path = norm(str(f.get("path", "")))
        fid = f.get("finding_id") or f"issue{i:04d}"
        ls = f.get("line_start")
        le = f.get("line_end") or ls
        touched = path in by_path
        bucket, hits, matched_phrases = "osoji_only_untouched_file", [], []
        message = f.get("message") or ""
        if touched:
            # 1. Phrase anchor: the false claim the finding quotes appears in
            #    the text #643 removed. Strongest mechanical signal.
            for ph in phrases_of(message):
                for h in by_path[path]:
                    if ph in h["_removed_full"]:
                        hits.append(h["hunk_id"])
                        matched_phrases.append(ph)
            hits = list(dict.fromkeys(hits))
            if hits:
                bucket = "candidate_hit_phrase"
            elif ls is None:
                bucket = "candidate_hit_file_level"
                hits = [h["hunk_id"] for h in by_path[path]]
            else:
                lo, hi = int(ls) - args.window, int(le) + args.window
                hits = [h["hunk_id"] for h in by_path[path]
                        if not (h["old_end"] < lo or h["old_start"] > hi)]
                bucket = "candidate_hit_line" if hits else "osoji_only_touched_file"
        for h in hits:
            matched_by_hunk[h].append(fid)
        f_rows.append({
            "finding_id": fid, "path": path, "line_start": ls, "line_end": le,
            "category": f.get("category"), "severity": f.get("severity"),
            "verdict": f.get("verdict"), "confidence": f.get("confidence"),
            "bucket": bucket, "matched_hunks": ";".join(hits),
            "matched_phrases": " | ".join(dict.fromkeys(matched_phrases))[:200],
            "message": message[:300].replace("\n", " "),
            "adjudication": "", "notes": "",
        })

    h_rows = []
    for h in hunks:
        m = matched_by_hunk.get(h["hunk_id"], [])
        row = {k: v for k, v in h.items() if not k.startswith("_")}
        h_rows.append({**row, "bucket": "matched" if m else "diff_only",
                       "matched_findings": ";".join(m),
                       "partition": "", "domain": "", "notes": ""})

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "findings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(f_rows[0].keys()) if f_rows else ["finding_id"])
        w.writeheader()
        w.writerows(f_rows)
    with (args.out / "hunks.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(h_rows[0].keys()) if h_rows else ["hunk_id"])
        w.writeheader()
        w.writerows(h_rows)
    in_diff = {r["path"] for r in f_rows if r["bucket"] != "osoji_only_untouched_file"}
    summary = {
        "base": args.base, "head": args.head, "window": args.window,
        "findings_total": len(f_rows),
        "findings_by_bucket": dict(Counter(r["bucket"] for r in f_rows)),
        "hunks_total": len(h_rows), "hunks_excluded": len(excluded),
        "hunks_by_bucket": dict(Counter(r["bucket"] for r in h_rows)),
        "diff_files": len(by_path), "renames": renames,
        "files_with_findings_in_diff": len(in_diff),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
