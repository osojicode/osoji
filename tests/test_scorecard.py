"""Tests for scorecard tabulation logic."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.debris import DocAnalysisResult, DocFinding
from docstar.scorecard import (
    CoverageEntry,
    Scorecard,
    build_scorecard,
    format_scorecard_markdown,
    scorecard_to_json,
    serialize_scorecard,
)


@pytest.fixture
def temp_dir():
    dir_path = Path(tempfile.mkdtemp())
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def config(temp_dir):
    return Config(root_path=temp_dir)


def _create_shadow_doc(config, relative_source_path):
    """Create a stub shadow doc so the source appears in the inventory."""
    shadow_path = config.shadow_root / (relative_source_path + ".shadow.md")
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_path.write_text(f"# {relative_source_path}\n@source-hash: abc123\n\nShadow doc content.")


def _create_findings_file(config, relative_source_path, findings):
    """Create a findings JSON file."""
    findings_path = config.findings_path_for(config.root_path / relative_source_path)
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": relative_source_path,
        "source_hash": "abc123",
        "generated": "2024-01-01T00:00:00Z",
        "findings": findings,
    }
    findings_path.write_text(json.dumps(data), encoding="utf-8")


def _create_signature(config, relative_source_path, purpose, topics):
    """Create a topic signature file."""
    sig_path = config.root_path / ".docstar" / "signatures" / (relative_source_path + ".signature.json")
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"path": relative_source_path, "kind": "source", "purpose": purpose, "topics": topics}
    sig_path.write_text(json.dumps(data), encoding="utf-8")


# --- Coverage calculation tests ---


class TestCoverageCalculation:
    def test_full_coverage(self, config):
        """Every module has at least one covering doc -> 100%."""
        _create_shadow_doc(config, "src/a.py")
        _create_shadow_doc(config, "src/b.py")

        results = [
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="API reference",
                matched_shadows=["src/a.py", "src/b.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.coverage_pct == 1.0
        assert len(scorecard.coverage_entries) == 2

    def test_partial_coverage(self, config):
        """Only some modules covered."""
        _create_shadow_doc(config, "src/a.py")
        _create_shadow_doc(config, "src/b.py")
        _create_shadow_doc(config, "src/c.py")

        results = [
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="tutorial",
                confidence=0.8,
                classification_reason="Tutorial",
                matched_shadows=["src/a.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert abs(scorecard.coverage_pct - 1 / 3) < 0.01

    def test_zero_coverage(self, config):
        """No docs at all -> 0%."""
        _create_shadow_doc(config, "src/a.py")
        _create_shadow_doc(config, "src/b.py")

        scorecard = build_scorecard(config, analysis_results=[])
        assert scorecard.coverage_pct == 0.0

    def test_no_source_files(self, config):
        """No shadow docs (no source files) -> handle gracefully."""
        results = [
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=[],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.coverage_pct == 0.0
        assert len(scorecard.coverage_entries) == 0

    def test_debris_docs_excluded_from_coverage(self, config):
        """Docs classified as debris don't count as coverage."""
        _create_shadow_doc(config, "src/a.py")

        results = [
            DocAnalysisResult(
                path=Path("docs/old-notes.md"),
                classification="process_artifact",
                confidence=0.95,
                classification_reason="One-time meeting notes",
                matched_shadows=["src/a.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.coverage_pct == 0.0  # debris excluded


# --- Coverage by Diataxis type ---


class TestCoverageByType:
    def test_coverage_by_type_breakdown(self, config):
        _create_shadow_doc(config, "src/a.py")
        _create_shadow_doc(config, "src/b.py")
        _create_shadow_doc(config, "src/c.py")
        _create_shadow_doc(config, "src/d.py")

        results = [
            DocAnalysisResult(
                path=Path("docs/ref.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=["src/a.py", "src/b.py"],
            ),
            DocAnalysisResult(
                path=Path("docs/tut.md"),
                classification="tutorial",
                confidence=0.8,
                classification_reason="Tutorial",
                matched_shadows=["src/a.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)

        # reference covers a.py and b.py -> 2/4 = 50%
        assert abs(scorecard.coverage_by_type["reference"] - 0.5) < 0.01
        # tutorial covers a.py -> 1/4 = 25%
        assert abs(scorecard.coverage_by_type["tutorial"] - 0.25) < 0.01
        # how-to and explanatory not present -> 0%
        assert scorecard.coverage_by_type["how-to"] == 0.0
        assert scorecard.coverage_by_type["explanatory"] == 0.0


# --- Dead docs ---


class TestDeadDocs:
    def test_dead_doc_filtering(self, config):
        results = [
            DocAnalysisResult(
                path=Path("docs/old.md"),
                classification="process_artifact",
                confidence=0.95,
                classification_reason="Meeting notes",
                matched_shadows=[],
            ),
            DocAnalysisResult(
                path=Path("docs/good.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="API reference",
                matched_shadows=[],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.dead_docs == ["docs/old.md"]


# --- Accuracy ---


class TestAccuracy:
    def test_accuracy_averaging(self, config):
        """Correct denominator: live docs, not total docs."""
        results = [
            DocAnalysisResult(
                path=Path("docs/debris.md"),
                classification="process_artifact",
                confidence=0.95,
                classification_reason="Debris",
                matched_shadows=[],
                findings=[
                    DocFinding(
                        category="stale_content",
                        severity="error",
                        description="Old content",
                        shadow_ref="src/a.py",
                        evidence="...",
                        remediation="Fix",
                    ),
                ],
            ),
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=[],
                findings=[
                    DocFinding(
                        category="stale_content",
                        severity="error",
                        description="Stale",
                        shadow_ref="src/a.py",
                        evidence="...",
                        remediation="Fix",
                    ),
                    DocFinding(
                        category="incorrect_content",
                        severity="error",
                        description="Wrong",
                        shadow_ref="src/b.py",
                        evidence="...",
                        remediation="Fix",
                    ),
                ],
            ),
            DocAnalysisResult(
                path=Path("docs/b.md"),
                classification="tutorial",
                confidence=0.8,
                classification_reason="Tutorial",
                matched_shadows=[],
                findings=[],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        # live docs = 2 (debris excluded)
        assert scorecard.live_doc_count == 2
        # errors from live docs only: a.md has 2 errors, b.md has 0 -> 2
        assert scorecard.total_accuracy_errors == 2
        assert scorecard.accuracy_errors_per_doc == 1.0
        assert scorecard.accuracy_by_category == {"stale_content": 1, "incorrect_content": 1}

    def test_accuracy_warnings_not_counted(self, config):
        """Only error-severity findings count for accuracy."""
        results = [
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=[],
                findings=[
                    DocFinding(
                        category="stale_content",
                        severity="warning",
                        description="Minor",
                        shadow_ref="src/a.py",
                        evidence="...",
                        remediation="Fix",
                    ),
                ],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.total_accuracy_errors == 0
        assert scorecard.accuracy_errors_per_doc == 0.0


# --- Hygiene ---


class TestHygiene:
    def test_hygiene_from_findings_files(self, config):
        _create_findings_file(config, "src/a.py", [
            {"category": "stale_comment", "severity": "warning", "description": "Stale", "line_start": 10, "line_end": 12},
            {"category": "misleading_docstring", "severity": "warning", "description": "Misleading", "line_start": 20, "line_end": 25},
        ])
        _create_findings_file(config, "src/b.py", [
            {"category": "expired_todo", "severity": "warning", "description": "TODO expired", "line_start": 5, "line_end": 5},
        ])

        scorecard = build_scorecard(config, analysis_results=[])
        assert scorecard.total_hygiene_warnings == 3
        assert scorecard.source_file_count == 2
        assert scorecard.hygiene_warnings_per_file == 1.5
        assert scorecard.hygiene_by_category == {
            "stale_comment": 1,
            "misleading_docstring": 1,
            "expired_todo": 1,
        }

    def test_hygiene_errors_not_counted(self, config):
        """Only warning-severity findings count for hygiene."""
        _create_findings_file(config, "src/a.py", [
            {"category": "dead_code", "severity": "error", "description": "Dead", "line_start": 10, "line_end": 20},
        ])

        scorecard = build_scorecard(config, analysis_results=[])
        assert scorecard.total_hygiene_warnings == 0


# --- Signatures ---


class TestSignatures:
    def test_missing_signatures_handled(self, config):
        """Coverage works even without signatures."""
        _create_shadow_doc(config, "src/a.py")

        results = [
            DocAnalysisResult(
                path=Path("docs/a.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=["src/a.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        assert scorecard.coverage_pct == 1.0
        assert scorecard.coverage_entries[0].topic_signature is None

    def test_signatures_loaded_when_present(self, config):
        """Signature files are loaded into coverage entries."""
        _create_shadow_doc(config, "src/a.py")
        _create_signature(config, "src/a.py", "Handles authentication", ["JWT", "OAuth"])

        results = [
            DocAnalysisResult(
                path=Path("docs/auth.md"),
                classification="reference",
                confidence=0.9,
                classification_reason="Reference",
                matched_shadows=["src/a.py"],
            ),
        ]

        scorecard = build_scorecard(config, analysis_results=results)
        entry = scorecard.coverage_entries[0]
        assert entry.topic_signature is not None
        assert entry.topic_signature["purpose"] == "Handles authentication"
        assert entry.topic_signature["topics"] == ["JWT", "OAuth"]


# --- Empty audit ---


class TestEmptyAudit:
    def test_empty_audit_produces_valid_scorecard(self, config):
        """No docs, no findings -> valid scorecard with zeros."""
        scorecard = build_scorecard(config, analysis_results=[])
        assert scorecard.coverage_pct == 0.0
        assert scorecard.coverage_entries == []
        assert scorecard.dead_docs == []
        assert scorecard.total_accuracy_errors == 0
        assert scorecard.live_doc_count == 0
        assert scorecard.accuracy_errors_per_doc == 0.0
        assert scorecard.total_hygiene_warnings == 0
        assert scorecard.source_file_count == 0
        assert scorecard.hygiene_warnings_per_file == 0.0


# --- Serialization ---


class TestSerialization:
    def test_serialize_scorecard_creates_file(self, config):
        scorecard = Scorecard(
            coverage_pct=0.73,
            dead_docs=["docs/old.md"],
            total_accuracy_errors=5,
            live_doc_count=10,
            accuracy_errors_per_doc=0.5,
        )
        serialize_scorecard(scorecard, config)

        out_path = config.root_path / ".docstar" / "analysis" / "scorecard.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["coverage_pct"] == 0.73
        assert data["dead_docs"] == ["docs/old.md"]


# --- Formatting ---


class TestFormatting:
    def test_markdown_rendering(self, config):
        scorecard = Scorecard(
            coverage_pct=0.73,
            coverage_by_type={"reference": 0.68, "tutorial": 0.22},
            dead_docs=["docs/old.md"],
            total_accuracy_errors=5,
            live_doc_count=10,
            accuracy_errors_per_doc=0.5,
            accuracy_by_category={"stale_content": 3, "incorrect_content": 2},
            total_hygiene_warnings=20,
            source_file_count=50,
            hygiene_warnings_per_file=0.4,
            hygiene_by_category={"stale_comment": 12, "expired_todo": 8},
            coverage_entries=[
                CoverageEntry(source_path="src/a.py", topic_signature=None, covering_docs=[{"path": "docs/a.md", "classification": "reference"}]),
            ],
        )

        md = format_scorecard_markdown(scorecard)
        assert "## Documentation Scorecard" in md
        assert "73%" in md
        assert "docs/old.md" in md
        assert "Stale Content" in md
        assert "Expired Todo" in md

    def test_json_conversion(self, config):
        scorecard = Scorecard(
            coverage_pct=0.5,
            coverage_entries=[
                CoverageEntry(source_path="src/a.py", topic_signature=None, covering_docs=[]),
            ],
        )

        data = scorecard_to_json(scorecard)
        assert data["coverage_pct"] == 0.5
        assert len(data["coverage_entries"]) == 1
        assert data["coverage_entries"][0]["source_path"] == "src/a.py"
