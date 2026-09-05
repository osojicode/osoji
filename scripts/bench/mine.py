"""Mine docs-fix commits into benchmark rows (wiki specs/0005, Phase 0.1).

A *docs-fix commit* is a non-merge commit that touched only documentation
files and modified or removed existing lines. Its parent is a repository
state in which those lines were wrong, so every corrected hunk group is a
row a documentation checker could have flagged. Rows are emitted unlabeled
(``labels: null``); ``bench.label`` assigns partition, domain, kind and
claim shape, and only then does a row count toward recall.

Usage:
    python scripts/bench/mine.py --repo <clone> --name <short-name> \
        [--since "24 months ago"] [--max-files 20] --out bench/<short-name>

Writes ``commits.jsonl`` (one line per docs-fix commit) and ``rows.jsonl``
(one line per kept hunk group). Row schema is a superset of the PR #643
inventory used by ``scripts/join_inventory_findings.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".txt", ".adoc"})
# Files whose doc-ness is real but whose edits are never claims about the
# code: release notes, legal text, community boilerplate.
_EXCLUDED_STEMS = re.compile(
    r"^(changelog|changes|history|news|release[-_]?notes|license|licence|"
    r"copying|notice|code[-_]of[-_]conduct|contributors|authors)$",
    re.IGNORECASE,
)
_EXCLUDED_DIRS = frozenset({
    "node_modules", "changelog.d", "changelog", "vendor", "dist", "build",
    "third_party", "site-packages", ".git",
})
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_RENAME_RE = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")
_COSMETIC_STRIP = re.compile(r"[\s`*_~.,;:!\"'()\[\]]+")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout


def norm_path(path: str) -> str:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def is_doc_path(path: str) -> bool:
    """True for documentation files whose edits can be claims about the code."""

    parts = norm_path(path).split("/")
    if any(part in _EXCLUDED_DIRS for part in parts[:-1]):
        return False
    name = Path(parts[-1])
    if name.suffix.lower() not in DOC_SUFFIXES:
        return False
    return not _EXCLUDED_STEMS.match(name.stem)


@dataclass
class CommitInfo:
    sha: str
    parent: str
    date: str
    subject: str
    files: list[str]
    insertions: int
    deletions: int


def _numstat_path(raw: str) -> str:
    """Resolve git's rename notation (``dir/{old => new}.md``, ``a => b``) to the new path."""

    m = _RENAME_RE.match(raw)
    if m:
        return norm_path(f"{m.group(1)}{m.group(3)}{m.group(4)}")
    if " => " in raw:
        return norm_path(raw.split(" => ", 1)[1])
    return norm_path(raw)


def list_docs_only_commits(
    repo: Path, since: str | None, max_files: int = 20, until: str | None = None,
) -> list[CommitInfo]:
    """Non-merge commits that touched only docs and removed or changed lines."""

    args = ["log", "--no-merges", "--format=%x1e%H%x1f%P%x1f%cI%x1f%s", "--numstat"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    out = _git(repo, *args)

    commits: list[CommitInfo] = []
    for block in out.split("\x1e"):
        block = block.strip("\n")
        if not block:
            continue
        header, _, body = block.partition("\n")
        sha, parents, date, subject = header.split("\x1f", 3)
        parent_list = parents.split()
        if len(parent_list) != 1:
            continue
        files: list[str] = []
        ins = dels = 0
        binary = False
        for line in body.splitlines():
            if not line.strip():
                continue
            cols = line.split("\t")
            if len(cols) < 3:
                continue
            if cols[0] == "-" or cols[1] == "-":
                binary = True
                break
            ins += int(cols[0])
            dels += int(cols[1])
            files.append(_numstat_path(cols[2]))
        if binary or not files or len(files) > max_files:
            continue
        if not all(is_doc_path(f) for f in files):
            continue
        if dels == 0:
            continue  # pure addition: nothing was wrong at the parent
        commits.append(CommitInfo(
            sha=sha, parent=parent_list[0], date=date, subject=subject,
            files=files, insertions=ins, deletions=dels,
        ))
    return commits


@dataclass
class Hunk:
    path: str
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    minus_text: list[str]
    plus_text: list[str]
    context_before: list[str]
    context_after: list[str]
    renamed_to: str | None = None


def _parent_lines(repo: Path, parent: str, path: str, cache: dict[str, list[str]]) -> list[str]:
    if path not in cache:
        try:
            cache[path] = _git(repo, "show", f"{parent}:{path}").splitlines()
        except subprocess.CalledProcessError:
            cache[path] = []
    return cache[path]


def parse_hunks(repo: Path, parent: str, commit: str, context: int = 5) -> list[Hunk]:
    """Hunks of ``parent..commit`` with old-side ranges and parent-side context."""

    out = _git(repo, "diff", "-M", "--unified=0", parent, commit)
    hunks: list[Hunk] = []
    cache: dict[str, list[str]] = {}
    old_path: str | None = None
    new_path: str | None = None
    cur: Hunk | None = None

    def flush() -> None:
        nonlocal cur
        if cur is None:
            return
        lines = _parent_lines(repo, parent, cur.path, cache)
        if cur.old_len == 0:
            # Insertion after line old_start (git's convention for empty old ranges).
            before_end = cur.old_start
            after_start = cur.old_start
        else:
            before_end = cur.old_start - 1
            after_start = cur.old_start - 1 + cur.old_len
        cur.context_before = lines[max(0, before_end - context):before_end]
        cur.context_after = lines[after_start:after_start + context]
        hunks.append(cur)
        cur = None

    for line in out.splitlines():
        if line.startswith("diff --git"):
            flush()
            old_path = new_path = None
        elif line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else norm_path(line[6:])
        elif line.startswith("+++ "):
            new_path = None if line[4:] == "/dev/null" else norm_path(line[6:])
        elif line.startswith("@@"):
            flush()
            m = _HUNK_RE.match(line)
            if not m or old_path is None:
                continue  # new files carry no old-side claim
            old_len = 1 if m.group(2) is None else int(m.group(2))
            new_len = 1 if m.group(4) is None else int(m.group(4))
            cur = Hunk(
                path=old_path, old_start=int(m.group(1)), old_len=old_len,
                new_start=int(m.group(3)), new_len=new_len,
                minus_text=[], plus_text=[], context_before=[], context_after=[],
                renamed_to=new_path if new_path and new_path != old_path else None,
            )
        elif cur is not None:
            if line.startswith("-"):
                cur.minus_text.append(line[1:].rstrip())
            elif line.startswith("+"):
                cur.plus_text.append(line[1:].rstrip())
    flush()
    return hunks


def group_hunks(hunks: list[Hunk], gap: int = 3) -> list[dict]:
    """Merge hunks on the same path within ``gap`` lines into one row."""

    indexed = sorted(enumerate(hunks, start=1), key=lambda ih: (ih[1].path, ih[1].old_start))
    rows: list[dict] = []
    for seq, h in indexed:
        end = h.old_start + max(h.old_len, 1) - 1
        if rows:
            r = rows[-1]
            if r["path"] == h.path and h.old_start <= r["_end"] + gap + 1:
                r["hunk_count"] += 1
                r["hunk_seqs"].append(seq)
                r["old_starts"].append(h.old_start)
                r["old_len"] = end - r["old_start"] + 1
                r["minus_text"].extend(h.minus_text)
                r["plus_text"].extend(h.plus_text)
                r["context_after"] = h.context_after
                r["_end"] = max(r["_end"], end)
                continue
        rows.append({
            "path": h.path, "renamed_to": h.renamed_to,
            "old_start": h.old_start, "old_len": max(h.old_len, 1),
            "new_start": h.new_start, "new_len": h.new_len,
            "hunk_count": 1, "hunk_seqs": [seq], "old_starts": [h.old_start],
            "minus_text": list(h.minus_text), "plus_text": list(h.plus_text),
            "context_before": h.context_before, "context_after": h.context_after,
            "_end": end,
        })
    for r in rows:
        r.pop("_end")
        r["minus_lines"] = len(r["minus_text"])
        r["plus_lines"] = len(r["plus_text"])
    return rows


def _cosmetic_key(lines: list[str]) -> str:
    return _COSMETIC_STRIP.sub("", " ".join(lines)).lower()


def prefilter_reason(row: dict) -> str | None:
    """Why a row cannot be a correction, or None if it might be."""

    if not row["minus_text"]:
        return "addition"
    if row["plus_text"] and _cosmetic_key(row["minus_text"]) == _cosmetic_key(row["plus_text"]):
        return "cosmetic"
    return None


def mine_repo(
    repo: Path, *, repo_name: str, since: str | None, out_dir: Path,
    max_files: int = 20, gap: int = 3, context: int = 5, until: str | None = None,
) -> dict:
    """Write ``commits.jsonl`` and ``rows.jsonl`` for one repository."""

    commits = list_docs_only_commits(repo, since=since, max_files=max_files, until=until)
    out_dir.mkdir(parents=True, exist_ok=True)
    dropped: Counter[str] = Counter()
    n_rows = 0
    with (out_dir / "commits.jsonl").open("w", encoding="utf-8") as cf, \
         (out_dir / "rows.jsonl").open("w", encoding="utf-8") as rf:
        for c in commits:
            kept = 0
            for row in group_hunks(parse_hunks(repo, c.parent, c.sha, context=context), gap=gap):
                reason = prefilter_reason(row)
                if reason:
                    dropped[reason] += 1
                    continue
                kept += 1
                n_rows += 1
                rf.write(json.dumps({
                    "row_id": f"{repo_name}:{c.sha[:10]}:{kept}",
                    "repo": repo_name, "commit": c.sha, "parent": c.parent,
                    "commit_date": c.date, "subject": c.subject,
                    **row,
                    "labels": None,
                }, ensure_ascii=False) + "\n")
            cf.write(json.dumps({**asdict(c), "rows_kept": kept}, ensure_ascii=False) + "\n")
    return {"commits": len(commits), "rows": n_rows, "rows_dropped": dict(dropped)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path, help="local clone (partial clones are fine)")
    ap.add_argument("--name", required=True, help="short repo name used in row ids")
    ap.add_argument("--since", default="24 months ago")
    ap.add_argument("--until", default=None)
    ap.add_argument("--max-files", type=int, default=20)
    ap.add_argument("--gap", type=int, default=3)
    ap.add_argument("--context", type=int, default=5)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    summary = mine_repo(
        args.repo, repo_name=args.name, since=args.since, until=args.until,
        out_dir=args.out, max_files=args.max_files, gap=args.gap, context=args.context,
    )
    print(json.dumps({"repo": args.name, **summary}, indent=2))


if __name__ == "__main__":
    main()
