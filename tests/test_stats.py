"""Tests for stats report formatting."""

from pathlib import Path

from osoji.stats import FileStats, ProjectStats, format_stats_report


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
