"""Draw a stratified spot-check sample for reader-versus-owner agreement.

Phase 0.4 (wiki specs/0005): every precision number inherits the reader's
error, so the reader's agreement with the owner is measured on a fixed
sample and published with the number. This script draws that sample
deterministically (seeded, proportional across repos) and renders a
checklist the owner fills in.

Usage:
    python scripts/bench/sample.py [--bench bench] --reader sonnet-r1 [--n 30] [--seed 35] > checklist.md
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):  # run as `python scripts/bench/sample.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.score import label_of  # noqa: E402


def sample_rows(rows: list[dict], *, n: int, seed: int, reader: str | None) -> list[dict]:
    """Seeded sample of labeled rows, proportional per repo, at least one per repo."""

    labeled = [r for r in rows if label_of(r, reader)]
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in labeled:
        by_repo[r["repo"]].append(r)
    if not by_repo:
        return []
    rng = random.Random(seed)
    total = len(labeled)
    quotas = {repo: max(1, round(n * len(rs) / total)) for repo, rs in by_repo.items()}
    # trim or top up to exactly n, largest repos absorb the difference
    order = sorted(by_repo, key=lambda k: -len(by_repo[k]))
    while sum(quotas.values()) > n:
        for repo in order:
            if quotas[repo] > 1 and sum(quotas.values()) > n:
                quotas[repo] -= 1
    while sum(quotas.values()) < n:
        for repo in order:
            if quotas[repo] < len(by_repo[repo]) and sum(quotas.values()) < n:
                quotas[repo] += 1
        if all(quotas[r] >= len(by_repo[r]) for r in order):
            break
    picked: list[dict] = []
    for repo in sorted(by_repo):
        rs = sorted(by_repo[repo], key=lambda r: r["row_id"])
        picked.extend(rng.sample(rs, min(quotas[repo], len(rs))))
    return picked


def render_checklist(rows: list[dict], *, reader: str | None) -> str:
    lines = ["| row | doc:line | removed → added | reader: partition / domain / kind / shape | reader's claim | owner |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        label = label_of(r, reader) or {}
        removed = " ⏎ ".join(r.get("minus_text") or [])[:140].replace("|", "\\|")
        added = " ⏎ ".join(r.get("plus_text") or [])[:140].replace("|", "\\|")
        lines.append(
            f"| {r['row_id']} | {r['path']}:{r['old_start']} | −{removed} → +{added} | "
            f"{label.get('partition')} / {label.get('domain')} / {label.get('kind')} / {label.get('claim_shape')} | "
            f"{(label.get('claim') or '')[:200].replace('|', chr(92) + '|')} |  |"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", type=Path, default=Path("bench"))
    ap.add_argument("--reader", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=35)
    ap.add_argument("--json", action="store_true", help="emit the sampled rows as JSONL instead of markdown")
    args = ap.parse_args()

    cfg = tomllib.loads((args.bench / "repos.toml").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for repo in cfg.get("repo", []):
        path = args.bench / repo["name"] / "rows.labeled.jsonl"
        if path.exists():
            rows.extend(json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
    picked = sample_rows(rows, n=args.n, seed=args.seed, reader=args.reader)
    if args.json:
        for r in picked:
            print(json.dumps(r, ensure_ascii=False))
    else:
        print(render_checklist(picked, reader=args.reader))


if __name__ == "__main__":
    main()
