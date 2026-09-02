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


def test_ignored_prefix_claim_produces_no_error_issue(temp_dir):
    """The whole point of the undecidable outlet: it must not reach the report.

    A doc naming a real, git-tracked file that the walker's discovery filter
    drops must not become an `error`-severity, confidence-1.0 issue that flips
    ``AuditResult.has_errors`` and propagates through export/push.
    """
    (temp_dir / ".github" / "workflows").mkdir(parents=True)
    (temp_dir / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    # A real `src/` so the missing file is anchored in the tree and stays
    # decidable (the anchor rule); the assertion under test is the .github one.
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
    (temp_dir / "README.md").write_text(
        "CI lives in `.github/workflows/ci.yml`; the missing one is `src/nope.ts`.\n",
        encoding="utf-8",
    )
    config = Config(root_path=temp_dir, respect_gitignore=False)

    issues, packets = tier_a_issues(config)

    by_name = {p.claim.name: p.verdict for p in packets}
    assert by_name[".github/workflows/ci.yml"] == "undecidable"
    assert by_name["src/nope.ts"] == "contradicted"
    assert [i.message for i in issues if ".github" in i.message] == []
    assert len(issues) == 1


def test_contradicted_path_claim_ships_as_a_warning_not_an_error(temp_dir):
    """Grade by kind (0027: masking grades severity, never gates).

    A missing npm script is a command that fails the moment a reader runs it;
    a path token in prose can be illustrative, quoted from another repo, or
    simply a shape the extractor over-reads. Both stay findings -- the path
    one is graded a warning so residual noise never flips ``has_errors`` on
    its own, and carries a confidence that says so.
    """
    (temp_dir / "src").mkdir()
    (temp_dir / "src" / "index.ts").write_text("export {}\n", encoding="utf-8")
    (temp_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    (temp_dir / "README.md").write_text(
        "Run `npm run test:ui`. See `src/nope.ts`.\n", encoding="utf-8"
    )
    config = Config(root_path=temp_dir, respect_gitignore=False)

    issues, _ = tier_a_issues(config)

    by_kind = {("script" if "script" in i.message else "path"): i for i in issues}
    assert by_kind["script"].severity == "error"
    assert by_kind["script"].confidence == 1.0
    assert by_kind["path"].severity == "warning"
    assert by_kind["path"].confidence == 0.8
    assert by_kind["path"].verdict == "confirmed"  # still a finding, just graded
