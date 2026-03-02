"""Regression tests for extract_doc_references (path normalization)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from docstar.config import Config
from docstar.shadow import extract_doc_references


def _setup_project(tmp_path: Path) -> Config:
    """Create a minimal project with a source file, shadow doc, and README."""
    # Source file
    src = tmp_path / "src" / "foo.py"
    src.parent.mkdir(parents=True)
    src.write_text("def hello(): pass\n", encoding="utf-8")

    # Shadow doc for the source file
    shadow = tmp_path / ".docstar" / "shadow" / "src" / "foo.py.shadow.md"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("# src/foo.py\n@source-hash: abc123\n", encoding="utf-8")

    # README that references the source file
    readme = tmp_path / "README.md"
    readme.write_text("# Project\nSee src/foo.py for details.\n", encoding="utf-8")

    return Config(root_path=tmp_path)


class TestExtractDocReferences:
    def test_no_crash_and_produces_facts(self, tmp_path):
        """extract_doc_references should not crash and should write correct facts."""
        config = _setup_project(tmp_path)
        files = [tmp_path / "README.md", tmp_path / "src" / "foo.py"]

        with patch("docstar.walker.list_repo_files", return_value=(files, False)):
            count = extract_doc_references(config, verbose=False)

        assert count == 1

        facts_path = config.facts_path_for(Path("README.md"))
        assert facts_path.exists()

        data = json.loads(facts_path.read_text(encoding="utf-8"))
        assert data["classification"] == "doc"
        assert len(data["imports"]) == 1
        assert data["imports"][0]["source"] == "src/foo.py"

    def test_relative_path_accepted(self, tmp_path):
        """facts_path_for should accept relative paths without crashing."""
        config = _setup_project(tmp_path)
        rel = Path("src/foo.py")
        abs_ = tmp_path / "src" / "foo.py"

        # Both should produce the same result
        assert config.facts_path_for(rel) == config.facts_path_for(abs_)

    def test_all_path_for_methods_accept_both(self, tmp_path):
        """All *_path_for methods should accept both absolute and relative paths."""
        config = Config(root_path=tmp_path)
        rel = Path("src/foo.py")
        abs_ = tmp_path / "src" / "foo.py"

        assert config.shadow_path_for(rel) == config.shadow_path_for(abs_)
        assert config.findings_path_for(rel) == config.findings_path_for(abs_)
        assert config.symbols_path_for(rel) == config.symbols_path_for(abs_)
        assert config.facts_path_for(rel) == config.facts_path_for(abs_)
        assert config.signatures_path_for(rel) == config.signatures_path_for(abs_)

        rel_dir = Path("src")
        abs_dir = tmp_path / "src"
        assert config.shadow_path_for_dir(rel_dir) == config.shadow_path_for_dir(abs_dir)
        assert config.signatures_path_for_dir(rel_dir) == config.signatures_path_for_dir(abs_dir)

        assert config.analysis_docs_path_for(rel) == config.analysis_docs_path_for(abs_)
        assert config.analysis_deadcode_path_for(rel) == config.analysis_deadcode_path_for(abs_)
        assert config.analysis_plumbing_path_for(rel) == config.analysis_plumbing_path_for(abs_)
        assert config.analysis_junk_path_for("test", rel) == config.analysis_junk_path_for("test", abs_)
