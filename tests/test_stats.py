"""Tests for stats formatting and provider-aware fallback behavior."""

import asyncio
from pathlib import Path

from osoji.config import Config
from osoji.llm import estimate_tokens_offline
from osoji.stats import FileStats, ProjectStats, format_stats_report, gather_stats_async


def test_format_stats_report_shows_zero_percent_ratio():
    stats = ProjectStats(
        files=[
            FileStats(
                source_path=Path("src/a.py"),
                shadow_path=Path(".osoji/shadow/src/a.py.shadow.md"),
                source_tokens=100,
                shadow_tokens=0,
                shadow_exists=True,
            )
        ],
        used_api=False,
    )

    report = format_stats_report(stats, verbose=True)

    assert "0%" in report
    assert "(0%)" in report


class _FailingCounter:
    label = "LiteLLM model-aware tokenizer"
    cache_key_prefix = "openai:gpt-4.1-mini:LiteLLM model-aware tokenizer"

    async def count_text_async(self, text: str) -> int:
        raise RuntimeError("tokenizer unavailable")

    async def close(self) -> None:
        return None


def test_gather_stats_falls_back_to_offline_when_counter_fails(monkeypatch, tmp_path):
    source_path = tmp_path / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_content = "print('hello world')\n"
    source_path.write_text(source_content, encoding="utf-8")

    config = Config(
        root_path=tmp_path,
        provider="openai",
        model="gpt-4.1-mini",
        respect_gitignore=False,
    )
    shadow_path = config.shadow_path_for(source_path)
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_content = "# app\nShort shadow"
    shadow_path.write_text(shadow_content, encoding="utf-8")

    monkeypatch.setattr("osoji.stats.discover_files", lambda _config: [source_path])
    monkeypatch.setattr("osoji.stats.TokenCounter", lambda **kwargs: _FailingCounter())

    project_stats = asyncio.run(gather_stats_async(config))

    assert project_stats.used_api is False
    assert project_stats.counter_label == "offline estimation (~4 chars/token)"
    assert project_stats.files[0].source_tokens == estimate_tokens_offline(source_content)
    assert project_stats.files[0].shadow_tokens == estimate_tokens_offline(shadow_content)
