"""Summarize the benchmark: rows, labels and counting rows by split and taxonomy.

Usage:
    python scripts/bench/stats.py [--bench bench] [--reader sonnet-r1] [--markdown]

"Counting" rows are checkout-domain corrections and deletions — the recall
denominator. The ``other`` rate per closed set is reported because a rising
rate is the taxonomy asking for revision (osoji CLAUDE.md principle).
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):  # run as `python scripts/bench/stats.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.score import COUNTING_DOMAIN, COUNTING_PARTITIONS, label_of  # noqa: E402


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def summarize_bench(bench_dir: Path, *, reader: str | None) -> dict:
    repos_cfg = tomllib.loads((bench_dir / "repos.toml").read_text(encoding="utf-8"))
    repos: dict[str, dict] = {}
    splits: dict[str, Counter] = defaultdict(Counter)
    by_kind: Counter = Counter()
    by_shape: Counter = Counter()
    partition: Counter = Counter()
    domain: Counter = Counter()
    totals: Counter = Counter()

    for cfg in repos_cfg.get("repo", []):
        name = cfg["name"]
        rows = _rows(bench_dir / name / "rows.labeled.jsonl") or _rows(bench_dir / name / "rows.jsonl")
        entry = {"split": cfg.get("split"), "language": cfg.get("language"),
                 "rows": len(rows), "labeled": 0, "counting": 0, "by_shape": Counter()}
        for row in rows:
            label = label_of(row, reader)
            if not label:
                continue
            entry["labeled"] += 1
            partition[label.get("partition") or "other"] += 1
            if label.get("partition") in COUNTING_PARTITIONS:
                domain[label.get("domain") or "none"] += 1
            if label.get("partition") in COUNTING_PARTITIONS and label.get("domain") == COUNTING_DOMAIN:
                entry["counting"] += 1
                by_kind[label.get("kind") or "other"] += 1
                by_shape[label.get("claim_shape") or "other"] += 1
                entry["by_shape"][label.get("claim_shape") or "other"] += 1
        entry["by_shape"] = dict(entry["by_shape"])
        repos[name] = entry
        for key in ("rows", "labeled", "counting"):
            splits[cfg.get("split", "?")][key] += entry[key]
            totals[key] += entry[key]

    counting = totals["counting"]
    return {
        "reader": reader,
        "repos": repos,
        "splits": {k: dict(v) for k, v in splits.items()},
        "by_kind": dict(by_kind),
        "by_shape": dict(by_shape),
        "partition": dict(partition),
        "domain": dict(domain),
        "other_rate": {
            "kind": (by_kind.get("other", 0) / counting) if counting else None,
            "shape": (by_shape.get("other", 0) / counting) if counting else None,
        },
        "totals": dict(totals),
    }


def render_markdown(summary: dict) -> str:
    lines = ["| repo | split | language | rows | labeled | counting | shapes |", "|---|---|---|---:|---:|---:|---|"]
    for name, e in summary["repos"].items():
        shapes = ", ".join(f"{k} {v}" for k, v in sorted(e["by_shape"].items(), key=lambda kv: -kv[1]))
        lines.append(f"| {name} | {e['split']} | {e['language']} | {e['rows']} | {e['labeled']} | {e['counting']} | {shapes} |")
    t = summary["totals"]
    lines.append(f"| **total** | | | {t.get('rows', 0)} | {t.get('labeled', 0)} | {t.get('counting', 0)} | |")
    lines.append("")
    lines.append("Splits: " + "; ".join(f"{k}: {v.get('counting', 0)} counting of {v.get('rows', 0)} rows"
                                        for k, v in summary["splits"].items()))
    lines.append("Kinds: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["by_kind"].items(), key=lambda kv: -kv[1])))
    lines.append("Shapes: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["by_shape"].items(), key=lambda kv: -kv[1])))
    lines.append("Partitions: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["partition"].items(), key=lambda kv: -kv[1])))
    lines.append("Domains (corrections/deletions): " + ", ".join(f"{k} {v}" for k, v in sorted(summary["domain"].items(), key=lambda kv: -kv[1])))
    orate = summary["other_rate"]
    lines.append(f"Other rate: kind {orate['kind']:.3f}, shape {orate['shape']:.3f}" if orate["kind"] is not None else "Other rate: n/a")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench", type=Path, default=Path("bench"))
    ap.add_argument("--reader", default=None)
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    summary = summarize_bench(args.bench, reader=args.reader)
    print(render_markdown(summary) if args.markdown else json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
