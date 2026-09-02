"""Tier A issues reach the audit result without any LLM call."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from osoji.audit import AuditIssue, format_audit_report, run_audit_async, tier_a_issues
from osoji.config import Config

# Every LLM-driven phase off: phase 2a is mechanical, and phase 1's shadow
# *check* is static (fix_shadow=False), so these runs need no provider at all.
_LLM_PHASES = {"doc-analysis", "debris", "obligations"}


def _one_bad_claim(temp_dir: Path) -> Config:
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text("Run `npm run test:ui`.\n", encoding="utf-8")
    return Config(root_path=temp_dir, respect_gitignore=False, quiet=True)


def test_tier_a_issues_from_config(temp_dir):
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text("Run `npm run test:ui`.\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)

    issues, packets = tier_a_issues(config)

    (issue,) = issues
    assert isinstance(issue, AuditIssue)
    assert issue.category == "doc_nonexistent_artifact"
    assert issue.severity == "error"
    assert issue.exclude_key == "doc-claims"
    assert issue.origin == {"source": "static", "plugin": "tier_a"}
    assert issue.line_start == 1
    assert Path(issue.path).name == "README.md"
    assert "test:ui" in issue.message and "package.json#scripts" in issue.message
    assert len(packets) == 1
    assert (config.analysis_root / "claims" / "README.md.claims.json").exists()


def test_tier_a_respects_exclude(temp_dir):
    (temp_dir / "README.md").write_text("See `src/nope.ts`.\n", encoding="utf-8")
    config = Config(root_path=temp_dir, respect_gitignore=False)
    issues, packets = tier_a_issues(config, exclude={"doc-claims"})
    assert issues == [] and packets == []


# --- phase 2a wiring inside run_audit_async ----------------------------------


def test_phase_2a_contradicted_claim_reaches_the_audit_result(temp_dir):
    """The wiring, not just tier_a_issues: a contradicted claim becomes an issue."""
    config = _one_bad_claim(temp_dir)

    result = asyncio.run(run_audit_async(config, fix_shadow=False, exclude=_LLM_PHASES))

    (issue,) = [i for i in result.issues if i.exclude_key == "doc-claims"]
    assert issue.category == "doc_nonexistent_artifact"
    assert issue.severity == "error"
    assert "test:ui" in issue.message
    assert config.audit_degradations == []
    assert result.scorecard.degraded_phases is None


def test_phase_2a_failure_degrades_without_aborting_the_audit(temp_dir):
    """#160: a Tier A crash must not discard the other phases' completed work.

    Phase 2a runs outside the phases 2-4 ``gather(return_exceptions=True)``,
    so it carries its own degrade guard.
    """
    config = _one_bad_claim(temp_dir)

    with patch("osoji.audit.tier_a_issues", side_effect=AttributeError("boom")):
        result = asyncio.run(run_audit_async(config, fix_shadow=False, exclude=_LLM_PHASES))

    # The audit completed and every other phase's work survived.
    assert result is not None
    assert any(i.category == "missing_shadow" for i in result.issues)
    assert [i for i in result.issues if i.exclude_key == "doc-claims"] == []

    # The failure is recorded and visible rather than silent.
    assert config.audit_degradations == [{"phase": "doc-claims", "error": "boom"}]
    assert result.scorecard.degraded_phases == ["doc-claims"]
    assert "doc-claims" in format_audit_report(result)
