"""Audit orchestration (fixture excerpt for dead param regression test)."""

from .scorecard import build_scorecard


def run_audit(config, analysis_results, junk_results):
    """Build scorecard from audit results."""
    scorecard = build_scorecard(
        config,
        analysis_results=analysis_results,
        junk_results=junk_results if junk_results else None,
    )
    return scorecard
