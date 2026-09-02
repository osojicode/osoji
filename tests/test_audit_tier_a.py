"""Tier A issues reach the audit result without any LLM call."""

import json
from pathlib import Path

from osoji.audit import AuditIssue, tier_a_issues
from osoji.config import Config


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
