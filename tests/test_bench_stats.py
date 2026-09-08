"""Tests for the benchmark stats summarizer (bench Phase 0, wiki specs/0005)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from bench.stats import summarize_bench, render_markdown  # noqa: E402


def _label(partition="correction", domain="checkout", kind="false_statement", shape="behaviour"):
    return {"r1": {"partition": partition, "domain": domain, "kind": kind, "claim_shape": shape,
                   "claim": "c", "confidence": 0.8}}


def _bench(temp_dir):
    (temp_dir / "repos.toml").write_text(
        'version = 1\n[[repo]]\nname = "a"\nsplit = "dev"\nlanguage = "Python"\n'
        '[[repo]]\nname = "b"\nsplit = "holdout"\nlanguage = "Go"\n', encoding="utf-8")
    rows_a = [
        {"row_id": "a:1:1", "repo": "a", "labels": _label()},
        {"row_id": "a:1:2", "repo": "a", "labels": _label(kind="wrong_path", shape="path")},
        {"row_id": "a:1:3", "repo": "a", "labels": _label(partition="restructure", domain=None)},
        {"row_id": "a:1:4", "repo": "a", "labels": _label(domain="world", kind="stale_version", shape="value")},
        {"row_id": "a:1:5", "repo": "a", "labels": None},
    ]
    rows_b = [{"row_id": "b:1:1", "repo": "b", "labels": _label(kind="other", shape="other")}]
    for name, rows in (("a", rows_a), ("b", rows_b)):
        d = temp_dir / name
        d.mkdir()
        (d / "rows.labeled.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return temp_dir


def test_summarize_counts_by_split_and_taxonomy(temp_dir):
    s = summarize_bench(_bench(temp_dir), reader="r1")

    assert s["repos"]["a"]["rows"] == 5
    assert s["repos"]["a"]["labeled"] == 4
    assert s["repos"]["a"]["counting"] == 2          # checkout correction/deletion only
    assert s["repos"]["b"]["counting"] == 1
    assert s["splits"]["dev"]["counting"] == 2 and s["splits"]["holdout"]["counting"] == 1
    assert s["by_kind"]["false_statement"] == 1 and s["by_kind"]["wrong_path"] == 1
    assert s["by_shape"]["path"] == 1 and s["by_shape"]["other"] == 1
    assert s["partition"]["restructure"] == 1
    assert s["domain"]["world"] == 1
    assert s["other_rate"]["kind"] == 1 / 3          # among counting rows
    assert s["totals"] == {"rows": 6, "labeled": 5, "counting": 3}


def test_render_markdown_has_one_row_per_repo(temp_dir):
    md = render_markdown(summarize_bench(_bench(temp_dir), reader="r1"))
    assert "| a |" in md and "| b |" in md and "holdout" in md
