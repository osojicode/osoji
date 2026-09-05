"""Tests for the benchmark cost ledger (bench Phase 0.2, wiki specs/0005).

The spend meter is unreliable (work#90), so every experiment table gets its
cost column from ``.osoji/logs/llm-interactions.jsonl``: per-model calls and
tokens inside a time window, optionally restricted to one forced tool,
priced at a dated sticker table.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from bench.cost import PRICES_USD_PER_MTOK, summarize  # noqa: E402


def _rec(ts, model, tin, tout, tool=None):
    req = {"model": model, "messages": [], "max_tokens": 100}
    if tool:
        req["tool_choice"] = {"type": "tool", "name": tool}
    return {"timestamp": ts, "sequence": 1, "provider": "anthropic", "attempt": 1,
            "request": req, "response": {"input_tokens": tin, "output_tokens": tout, "model": model}}


def _log(temp_dir, records):
    p = temp_dir / "llm-interactions.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n", encoding="utf-8")
    return p


class TestSummarize:
    def test_window_and_pricing(self, temp_dir):
        log = _log(temp_dir, [
            _rec("2026-09-05T10:00:00Z", "claude-opus-4-6", 1_000_000, 100_000),
            _rec("2026-09-05T10:05:00Z", "claude-haiku-4-5-20251001", 2_000_000, 0),
            _rec("2026-09-05T12:00:00Z", "claude-opus-4-6", 5_000_000, 0),  # outside window
        ])

        s = summarize(log, since="2026-09-05T09:00:00Z", until="2026-09-05T11:00:00Z")

        opus_in, opus_out = PRICES_USD_PER_MTOK["claude-opus-4-6"]
        assert s["by_model"]["claude-opus-4-6"]["calls"] == 1
        assert s["by_model"]["claude-opus-4-6"]["sticker_usd"] == opus_in + 0.1 * opus_out
        assert s["by_model"]["claude-haiku-4-5-20251001"]["input_tokens"] == 2_000_000
        assert s["calls"] == 2
        assert s["sticker_usd"] == round(opus_in + 0.1 * opus_out + 2 * PRICES_USD_PER_MTOK["claude-haiku-4-5-20251001"][0], 4)

    def test_tool_filter(self, temp_dir):
        log = _log(temp_dir, [
            _rec("2026-09-05T10:00:00Z", "claude-sonnet-4-6", 10, 1, tool="label_doc_fix"),
            _rec("2026-09-05T10:01:00Z", "claude-sonnet-4-6", 10, 1, tool="analyze_document"),
        ])
        s = summarize(log, tool="label_doc_fix")
        assert s["calls"] == 1

    def test_unknown_model_is_counted_but_unpriced(self, temp_dir):
        log = _log(temp_dir, [_rec("2026-09-05T10:00:00Z", "mystery-model", 10, 1)])
        s = summarize(log)
        assert s["by_model"]["mystery-model"]["calls"] == 1
        assert s["by_model"]["mystery-model"]["sticker_usd"] is None
        assert s["unpriced_models"] == ["mystery-model"]

    def test_missing_log_is_empty(self, temp_dir):
        s = summarize(temp_dir / "nope.jsonl")
        assert s["calls"] == 0 and s["sticker_usd"] == 0.0
