"""Cost ledger from osoji's interaction log (wiki specs/0005, Phase 0.2).

The spend meter is unreliable (work#90), so the cost column of every
experiment table comes from ``.osoji/logs/llm-interactions.jsonl``: calls
and tokens per model inside a time window, optionally restricted to one
forced tool, priced at the dated sticker table below. Dashboard actuals
remain the reference; this is the per-run attribution the dashboard cannot
give.

Usage:
    python scripts/bench/cost.py [--log .osoji/logs/llm-interactions.jsonl] \
        [--since ISO] [--until ISO] [--tool label_doc_fix]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

#: Sticker prices, USD per million tokens (input, output). Dated 2026-09-05.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def summarize(
    log_path: Path, *, since: str | None = None, until: str | None = None, tool: str | None = None,
) -> dict:
    """Per-model calls, tokens and sticker cost for records in the window."""

    by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    if log_path.exists():
        with log_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("timestamp", "")
                if since and ts < since:
                    continue
                if until and ts >= until:
                    continue
                req = rec.get("request") or {}
                if tool and ((req.get("tool_choice") or {}).get("name") != tool):
                    continue
                resp = rec.get("response") or {}
                model = req.get("model") or resp.get("model") or "?"
                m = by_model[model]
                m["calls"] += 1
                m["input_tokens"] += int(resp.get("input_tokens") or 0)
                m["output_tokens"] += int(resp.get("output_tokens") or 0)

    total = 0.0
    unpriced: list[str] = []
    for model, m in by_model.items():
        price = PRICES_USD_PER_MTOK.get(model)
        if price is None:
            m["sticker_usd"] = None
            unpriced.append(model)
            continue
        m["sticker_usd"] = round(m["input_tokens"] / 1e6 * price[0] + m["output_tokens"] / 1e6 * price[1], 4)
        total += m["sticker_usd"]
    return {
        "calls": sum(m["calls"] for m in by_model.values()),
        "input_tokens": sum(m["input_tokens"] for m in by_model.values()),
        "output_tokens": sum(m["output_tokens"] for m in by_model.values()),
        "sticker_usd": round(total, 4),
        "by_model": dict(by_model),
        "unpriced_models": sorted(unpriced),
        "window": {"since": since, "until": until, "tool": tool},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, default=Path(".osoji/logs/llm-interactions.jsonl"))
    ap.add_argument("--since", default=None, help="ISO timestamp (UTC), inclusive")
    ap.add_argument("--until", default=None, help="ISO timestamp (UTC), exclusive")
    ap.add_argument("--tool", default=None, help="only calls that forced this tool")
    args = ap.parse_args()
    print(json.dumps(summarize(args.log, since=args.since, until=args.until, tool=args.tool), indent=2))


if __name__ == "__main__":
    main()
