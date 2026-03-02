"""Tests for audit report formatting: console tables, HTML report, and uncovered files."""

from pathlib import Path

import pytest

from docstar.audit import (
    AuditIssue,
    AuditResult,
    _format_scorecard_section,
    format_audit_html,
    serialize_audit_result,
    load_audit_result,
)
from docstar.scorecard import CoverageEntry, JunkCodeEntry, Scorecard


def _minimal_scorecard(**overrides) -> Scorecard:
    """Build a minimal Scorecard with defaults, overriding specific fields."""
    defaults = dict(
        coverage_entries=[],
        coverage_pct=0.0,
        covered_count=0,
        total_source_count=0,
        coverage_by_type={},
        type_covered_counts={},
        type_total_counts={},
        dead_docs=[],
        total_accuracy_errors=0,
        live_doc_count=0,
        accuracy_errors_per_doc=0.0,
        accuracy_by_category={},
        junk_total_lines=0,
        junk_total_source_lines=0,
        junk_fraction=0.0,
        junk_item_count=0,
        junk_file_count=0,
        junk_by_category={},
        junk_by_category_lines={},
        junk_entries=[],
        junk_sources=[],
        enforcement_total_obligations=None,
        enforcement_unactuated=None,
        enforcement_pct_unactuated=None,
        enforcement_by_schema=None,
    )
    defaults.update(overrides)
    return Scorecard(**defaults)


def _minimal_result(**sc_overrides) -> AuditResult:
    """Build a minimal AuditResult with a scorecard."""
    return AuditResult(issues=[], scorecard=_minimal_scorecard(**sc_overrides))


# --- Console tables (tabulate) ---

class TestConsoleTables:
    def test_simple_format_no_pipe_separators(self):
        """Tabulate 'simple' format should not contain pipe characters in table lines."""
        sc = _minimal_scorecard(
            coverage_pct=75.0, covered_count=3, total_source_count=4,
            accuracy_by_category={"stale_content": 2},
        )
        lines = _format_scorecard_section(sc)
        text = "\n".join(lines)
        # The summary table and accuracy table should use tabulate simple format
        # which uses dashes and spaces, not pipe characters for separators
        table_lines = [l for l in lines if l.strip() and not l.startswith("#")
                       and not l.startswith("*") and not l.startswith("-")]
        for line in table_lines:
            # Pipe characters should NOT appear as table delimiters
            # (they can appear in content like `--dead-code`)
            if line.startswith("|") and line.endswith("|"):
                pytest.fail(f"Found pipe-table line: {line}")

    def test_summary_table_contains_metrics(self):
        """Summary table contains all expected metric names."""
        sc = _minimal_scorecard(
            coverage_pct=81.0, covered_count=50, total_source_count=62,
        )
        lines = _format_scorecard_section(sc)
        text = "\n".join(lines)
        assert "Source file coverage" in text
        assert "81%" in text
        assert "50/62" in text
        assert "Dead docs (debris)" in text
        assert "Accuracy errors / live doc" in text
        assert "Junk code fraction" in text

    def test_doc_linkage_table_has_counts(self):
        """Doc linkage table shows linked/total columns."""
        sc = _minimal_scorecard(
            coverage_by_type={"how-to": 90.0, "reference": 50.0},
            type_covered_counts={"how-to": 9, "reference": 5},
            type_total_counts={"how-to": 10, "reference": 10},
        )
        lines = _format_scorecard_section(sc)
        text = "\n".join(lines)
        assert "Doc linkage by type" in text
        assert "Linked" in text
        assert "Total" in text


# --- Uncovered files section ---

class TestUncoveredFiles:
    def test_uncovered_files_listed(self):
        """Uncovered source files appear in the scorecard output."""
        entries = [
            CoverageEntry("src/a.py", {"purpose": "Auth handler"}, []),
            CoverageEntry("src/b.py", None, [{"path": "docs/b.md", "classification": "reference"}]),
        ]
        sc = _minimal_scorecard(
            coverage_entries=entries,
            covered_count=1, total_source_count=2, coverage_pct=50.0,
        )
        lines = _format_scorecard_section(sc)
        text = "\n".join(lines)
        assert "Uncovered source files" in text
        assert "`src/a.py`" in text
        assert "Auth handler" in text
        # Covered file should NOT appear
        assert "`src/b.py`" not in text

    def test_no_uncovered_files_omits_section(self):
        """When all files are covered, no uncovered section appears."""
        entries = [
            CoverageEntry("src/a.py", None, [{"path": "docs/a.md", "classification": "reference"}]),
        ]
        sc = _minimal_scorecard(
            coverage_entries=entries,
            covered_count=1, total_source_count=1, coverage_pct=100.0,
        )
        lines = _format_scorecard_section(sc)
        text = "\n".join(lines)
        assert "Uncovered source files" not in text


# --- HTML report ---

class TestHTMLReport:
    def test_html_structure(self):
        """HTML report has DOCTYPE, html tags, and expected sections."""
        sc = _minimal_scorecard(
            coverage_pct=75.0, covered_count=3, total_source_count=4,
            coverage_by_type={"reference": 100.0},
            type_covered_counts={"reference": 2},
            type_total_counts={"reference": 2},
            coverage_entries=[
                CoverageEntry("src/a.py", None, [{"path": "docs/a.md", "classification": "reference"}]),
            ],
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "section-coverage" in html
        assert "PASSED" in html

    def test_html_failed_badge(self):
        """HTML report shows FAILED when there are errors."""
        result = AuditResult(
            issues=[AuditIssue(Path("docs/a.md"), "error", "debris", "Bad", "Delete")],
            scorecard=_minimal_scorecard(),
        )
        html = format_audit_html(result)
        assert "FAILED" in html
        assert "badge-fail" in html

    def test_html_coverage_anchor(self):
        """Coverage section has the correct anchor."""
        sc = _minimal_scorecard(
            coverage_pct=50.0, covered_count=1, total_source_count=2,
            coverage_entries=[
                CoverageEntry("src/a.py", None, [{"path": "docs/a.md", "classification": "reference"}]),
                CoverageEntry("src/b.py", None, []),
            ],
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert 'id="section-coverage"' in html

    def test_html_coverage_matrix_with_types(self):
        """Coverage matrix shows checkmarks and crosses for doc types."""
        entries = [
            CoverageEntry("src/a.py", None, [
                {"path": "docs/ref.md", "classification": "reference"},
            ]),
        ]
        sc = _minimal_scorecard(
            coverage_pct=100.0, covered_count=1, total_source_count=1,
            coverage_entries=entries,
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        # Should have a checkmark for reference
        assert "&#10003;" in html  # checkmark
        assert "src/a.py" in html

    def test_html_coverage_matrix_source_reference_only(self):
        """Source covered by reference only shows green for reference, red for others."""
        entries = [
            CoverageEntry("src/a.py", None, [
                {"path": "docs/ref.md", "classification": "reference"},
                {"path": "docs/howto.md", "classification": "how-to"},
            ]),
            CoverageEntry("src/b.py", None, [
                {"path": "docs/ref2.md", "classification": "reference"},
            ]),
        ]
        sc = _minimal_scorecard(
            coverage_pct=100.0, covered_count=2, total_source_count=2,
            coverage_entries=entries,
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        # src/b.py should have a cross for how-to
        assert "&#10007;" in html  # cross mark

    def test_html_large_matrix_collapsed(self):
        """Coverage matrix with >50 entries wrapped in <details>."""
        entries = [
            CoverageEntry(f"src/file{i}.py", None, [
                {"path": f"docs/ref{i}.md", "classification": "reference"},
            ])
            for i in range(55)
        ]
        sc = _minimal_scorecard(
            coverage_pct=100.0, covered_count=55, total_source_count=55,
            coverage_entries=entries,
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert "<details>" in html
        assert "Coverage matrix (55 files)" in html

    def test_html_no_junk_omits_section(self):
        """When no junk data, junk section is omitted."""
        result = _minimal_result()
        html = format_audit_html(result)
        assert 'id="section-junk"' not in html

    def test_html_no_enforcement_omits_section(self):
        """When enforcement is None, enforcement section is omitted."""
        result = _minimal_result()
        html = format_audit_html(result)
        assert 'id="section-enforcement"' not in html

    def test_html_enforcement_present(self):
        """When enforcement data exists, section is rendered."""
        sc = _minimal_scorecard(
            enforcement_total_obligations=10,
            enforcement_unactuated=2,
            enforcement_pct_unactuated=20.0,
            enforcement_by_schema={"src/schema.ts:Config": {"unactuated": 2, "fields": ["timeout", "retries"]}},
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert 'id="section-enforcement"' in html
        assert "timeout" in html
        assert "retries" in html

    def test_html_dead_docs_section(self):
        """Dead docs section renders when debris exists."""
        sc = _minimal_scorecard(dead_docs=["docs/old.md", "docs/stale.md"])
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert 'id="section-dead-docs"' in html
        assert "docs/old.md" in html
        assert "docs/stale.md" in html

    def test_html_no_dead_docs_omits_section(self):
        """No dead docs means no dead docs section."""
        result = _minimal_result(dead_docs=[])
        html = format_audit_html(result)
        assert 'id="section-dead-docs"' not in html

    def test_html_escapes_values(self):
        """HTML-sensitive characters are escaped."""
        entries = [
            CoverageEntry("src/<script>.py", None, []),
        ]
        sc = _minimal_scorecard(
            coverage_entries=entries,
            covered_count=0, total_source_count=1, coverage_pct=0.0,
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        # Should be escaped, not raw
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_well_formed_critical_tags(self):
        """Critical HTML tags are properly closed."""
        sc = _minimal_scorecard(
            coverage_pct=50.0, covered_count=1, total_source_count=2,
            dead_docs=["docs/old.md"],
            accuracy_by_category={"stale_content": 1},
            total_accuracy_errors=1, live_doc_count=1, accuracy_errors_per_doc=1.0,
            junk_by_category={"dead_code": 1},
            junk_by_category_lines={"dead_code": 5},
            junk_total_lines=5, junk_total_source_lines=100, junk_fraction=0.05,
            junk_item_count=1, junk_file_count=1,
        )
        result = AuditResult(
            issues=[AuditIssue(Path("docs/a.md"), "error", "doc_stale", "Stale", "Fix")],
            scorecard=sc,
        )
        html = format_audit_html(result)
        # Check paired tags
        for tag in ["html", "head", "body", "style", "table", "div"]:
            open_count = html.count(f"<{tag}")
            close_count = html.count(f"</{tag}>")
            assert open_count == close_count, f"Unbalanced <{tag}>: {open_count} opens, {close_count} closes"

    def test_html_metric_cards_link_to_sections(self):
        """Metric cards are links to section anchors."""
        sc = _minimal_scorecard(
            coverage_pct=75.0, covered_count=3, total_source_count=4,
        )
        result = AuditResult(issues=[], scorecard=sc)
        html = format_audit_html(result)
        assert 'href="#section-coverage"' in html
        assert 'href="#section-dead-docs"' in html
        assert 'href="#section-accuracy"' in html
        assert 'href="#section-junk"' in html


# --- Scorecard count fields ---

class TestScorecardCounts:
    def test_covered_and_total_match(self, temp_dir):
        """covered_count and total_source_count populated correctly."""
        from docstar.config import Config
        from docstar.scorecard import build_scorecard

        config = Config(root_path=temp_dir, respect_gitignore=False)

        # Create shadow inventory
        shadow_dir = temp_dir / ".docstar" / "shadow"
        for name in ["src/a.py", "src/b.py", "src/c.py"]:
            sf = shadow_dir / (name + ".shadow.md")
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(f"# {name}")
            src = temp_dir / name
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("pass\n")

        from docstar.doc_analysis import DocAnalysisResult
        results = [
            DocAnalysisResult(
                path=Path("docs/guide.md"), classification="how-to",
                confidence=0.9, classification_reason="test",
                matched_shadows=["src/a.py"], findings=[],
            ),
        ]
        sc = build_scorecard(config, results)
        assert sc.total_source_count == 3
        assert sc.covered_count == 1
        assert sc.coverage_pct == pytest.approx(100 / 3, abs=0.1)

    def test_type_counts_populated(self, temp_dir):
        """type_covered_counts and type_total_counts populated correctly."""
        from docstar.config import Config
        from docstar.scorecard import build_scorecard
        from docstar.doc_analysis import DocAnalysisResult

        config = Config(root_path=temp_dir, respect_gitignore=False)

        results = [
            DocAnalysisResult(
                path=Path("docs/guide.md"), classification="how-to",
                confidence=0.9, classification_reason="test",
                matched_shadows=["src/a.py"], findings=[],
            ),
            DocAnalysisResult(
                path=Path("docs/ref.md"), classification="reference",
                confidence=0.9, classification_reason="test",
                matched_shadows=[], findings=[],
            ),
            DocAnalysisResult(
                path=Path("docs/ref2.md"), classification="reference",
                confidence=0.9, classification_reason="test",
                matched_shadows=["src/b.py"], findings=[],
            ),
        ]
        sc = build_scorecard(config, results)
        assert sc.type_total_counts == {"how-to": 1, "reference": 2}
        assert sc.type_covered_counts == {"how-to": 1, "reference": 1}
        assert sc.coverage_by_type["how-to"] == 100.0
        assert sc.coverage_by_type["reference"] == 50.0

    def test_uncovered_entries_have_empty_covering_docs(self, temp_dir):
        """Uncovered entries have empty covering_docs list."""
        from docstar.config import Config
        from docstar.scorecard import build_scorecard

        config = Config(root_path=temp_dir, respect_gitignore=False)

        shadow_dir = temp_dir / ".docstar" / "shadow"
        for name in ["src/a.py", "src/b.py"]:
            sf = shadow_dir / (name + ".shadow.md")
            sf.parent.mkdir(parents=True, exist_ok=True)
            sf.write_text(f"# {name}")
            src = temp_dir / name
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("pass\n")

        sc = build_scorecard(config, [])
        assert sc.covered_count == 0
        for entry in sc.coverage_entries:
            assert entry.covering_docs == []


# --- Serialize / load round-trip ---

class TestAuditResultRoundTrip:
    def test_round_trip_basic(self, temp_dir):
        """AuditResult survives serialize → load with all fields intact."""
        from docstar.config import Config

        config = Config(root_path=temp_dir, respect_gitignore=False)
        original = AuditResult(
            issues=[
                AuditIssue(
                    path=Path("docs/guide.md"),
                    severity="error",
                    category="debris",
                    message="Stale doc",
                    remediation="Delete it",
                    line_start=10,
                    line_end=20,
                ),
                AuditIssue(
                    path=Path("src/utils.py"),
                    severity="warning",
                    category="stale_shadow",
                    message="Shadow is stale",
                    remediation="Run docstar shadow",
                ),
            ],
            scorecard=_minimal_scorecard(
                coverage_pct=75.0,
                covered_count=3,
                total_source_count=4,
                dead_docs=["docs/old.md"],
            ),
        )

        serialize_audit_result(config, original)
        loaded = load_audit_result(config)

        assert len(loaded.issues) == len(original.issues)
        assert loaded.issues[0].severity == "error"
        assert loaded.issues[0].category == "debris"
        assert loaded.issues[0].message == "Stale doc"
        assert loaded.issues[0].line_start == 10
        assert loaded.issues[0].line_end == 20
        assert loaded.issues[1].line_start is None
        assert loaded.scorecard.coverage_pct == 75.0
        assert loaded.scorecard.covered_count == 3
        assert loaded.scorecard.dead_docs == ["docs/old.md"]

    def test_missing_file_raises(self, temp_dir):
        """load_audit_result raises FileNotFoundError when no cache exists."""
        from docstar.config import Config

        config = Config(root_path=temp_dir, respect_gitignore=False)
        with pytest.raises(FileNotFoundError):
            load_audit_result(config)

    def test_path_objects_round_trip(self, temp_dir):
        """AuditIssue.path round-trips through str() → Path()."""
        from docstar.config import Config

        config = Config(root_path=temp_dir, respect_gitignore=False)
        original = AuditResult(
            issues=[
                AuditIssue(
                    path=Path("src/deep/nested/file.py"),
                    severity="warning",
                    category="test",
                    message="test",
                    remediation="test",
                ),
            ],
            scorecard=_minimal_scorecard(),
        )

        serialize_audit_result(config, original)
        loaded = load_audit_result(config)

        assert isinstance(loaded.issues[0].path, Path)
        assert loaded.issues[0].path == Path("src/deep/nested/file.py")

    def test_scorecard_nested_objects_round_trip(self, temp_dir):
        """CoverageEntry and JunkCodeEntry survive round-trip."""
        from docstar.config import Config

        config = Config(root_path=temp_dir, respect_gitignore=False)
        coverage_entries = [
            CoverageEntry(
                source_path="src/a.py",
                topic_signature={"purpose": "Auth handler"},
                covering_docs=[{"path": "docs/a.md", "classification": "reference"}],
            ),
            CoverageEntry(
                source_path="src/b.py",
                topic_signature=None,
                covering_docs=[],
            ),
        ]
        junk_entries = [
            JunkCodeEntry(
                source_path="src/c.py",
                total_lines=100,
                junk_lines=15,
                junk_fraction=0.15,
                items=[{"category": "dead_code", "line_start": 10, "line_end": 24}],
            ),
        ]
        original = AuditResult(
            issues=[],
            scorecard=_minimal_scorecard(
                coverage_entries=coverage_entries,
                junk_entries=junk_entries,
                obligation_violations=3,
                obligation_implicit_contracts=7,
            ),
        )

        serialize_audit_result(config, original)
        loaded = load_audit_result(config)

        # CoverageEntry
        assert len(loaded.scorecard.coverage_entries) == 2
        ce0 = loaded.scorecard.coverage_entries[0]
        assert ce0.source_path == "src/a.py"
        assert ce0.topic_signature == {"purpose": "Auth handler"}
        assert ce0.covering_docs == [{"path": "docs/a.md", "classification": "reference"}]
        ce1 = loaded.scorecard.coverage_entries[1]
        assert ce1.topic_signature is None
        assert ce1.covering_docs == []

        # JunkCodeEntry
        assert len(loaded.scorecard.junk_entries) == 1
        je0 = loaded.scorecard.junk_entries[0]
        assert je0.source_path == "src/c.py"
        assert je0.total_lines == 100
        assert je0.junk_lines == 15
        assert je0.junk_fraction == pytest.approx(0.15)
        assert je0.items == [{"category": "dead_code", "line_start": 10, "line_end": 24}]

        # Obligation fields
        assert loaded.scorecard.obligation_violations == 3
        assert loaded.scorecard.obligation_implicit_contracts == 7

    def test_passed_and_counts_preserved(self, temp_dir):
        """The passed/errors/warnings properties work correctly after round-trip."""
        from docstar.config import Config

        config = Config(root_path=temp_dir, respect_gitignore=False)
        original = AuditResult(
            issues=[
                AuditIssue(Path("a.md"), "error", "debris", "bad", "fix"),
                AuditIssue(Path("b.md"), "warning", "stale", "old", "update"),
                AuditIssue(Path("c.md"), "info", "note", "fyi", "none"),
            ],
            scorecard=_minimal_scorecard(),
        )

        serialize_audit_result(config, original)
        loaded = load_audit_result(config)

        assert loaded.has_errors is True
        assert loaded.has_warnings is True
        assert loaded.passed is False
