"""Tests for scorecard tabulation (pure Python, no LLM mocking needed)."""

import json
from pathlib import Path

import pytest

from docstar.config import Config
from docstar.debris import DocAnalysisResult, DocFinding
from docstar.deadcode import DeadCodeVerification
from docstar.plumbing import PlumbingResult, PlumbingVerification
from docstar.junk import JunkAnalysisResult, JunkFinding
from docstar.scorecard import (
    Scorecard,
    build_scorecard,
    merge_ranges,
)


# --- Helpers ---

def _write_shadow(temp_dir, source):
    """Create a minimal shadow doc so the source is inventoried."""
    shadow_dir = temp_dir / ".docstar" / "shadow"
    shadow_file = shadow_dir / (source + ".shadow.md")
    shadow_file.parent.mkdir(parents=True, exist_ok=True)
    shadow_file.write_text(f"# {source}\n@source-hash: abc\n\nShadow doc.")


def _write_source(temp_dir, path, content="# placeholder\n"):
    """Create a source file so line counting works."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _write_signature(temp_dir, source, purpose="Does things", topics=None):
    """Write a topic signature JSON."""
    sig_dir = temp_dir / ".docstar" / "signatures"
    sig_file = sig_dir / (source + ".signature.json")
    sig_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "path": source,
        "kind": "source",
        "purpose": purpose,
        "topics": topics or ["topic1", "topic2"],
        "public_surface": [],
    }
    sig_file.write_text(json.dumps(data))


def _write_findings(temp_dir, source, findings):
    """Write a findings JSON file for a source."""
    findings_dir = temp_dir / ".docstar" / "findings"
    findings_file = findings_dir / (source + ".findings.json")
    findings_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": source,
        "source_hash": "abc",
        "generated": "2025-01-01T00:00:00Z",
        "findings": findings,
    }
    findings_file.write_text(json.dumps(data))


def _make_analysis(path, classification="reference", matched_shadows=None,
                   findings=None, is_process_artifact=False, topic_sig=None):
    """Create a DocAnalysisResult for testing."""
    cls = "process_artifact" if is_process_artifact else classification
    return DocAnalysisResult(
        path=Path(path),
        classification=cls,
        confidence=0.9,
        classification_reason="test",
        matched_shadows=matched_shadows or [],
        findings=findings or [],
        topic_signature=topic_sig,
    )


def _make_finding(category="stale_content", severity="error"):
    """Create a DocFinding for testing."""
    return DocFinding(
        category=category,
        severity=severity,
        description="test finding",
        shadow_ref="src/foo.py",
        evidence="test evidence",
        remediation="fix it",
    )


# --- merge_ranges ---

class TestMergeRanges:
    def test_empty(self):
        assert merge_ranges([]) == []

    def test_non_overlapping(self):
        assert merge_ranges([(1, 3), (5, 7), (10, 12)]) == [(1, 3), (5, 7), (10, 12)]

    def test_overlapping(self):
        assert merge_ranges([(1, 5), (3, 8), (10, 12)]) == [(1, 8), (10, 12)]

    def test_adjacent(self):
        assert merge_ranges([(1, 3), (4, 6)]) == [(1, 6)]

    def test_fully_contained(self):
        assert merge_ranges([(1, 10), (3, 5)]) == [(1, 10)]

    def test_unsorted_input(self):
        assert merge_ranges([(5, 7), (1, 3)]) == [(1, 3), (5, 7)]

    def test_single_range(self):
        assert merge_ranges([(1, 1)]) == [(1, 1)]


# --- Coverage ---

class TestCoverage:
    def test_full_coverage(self, temp_dir):
        """All source files covered by docs → 100%."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_shadow(temp_dir, "src/b.py")
        _write_source(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/b.py")

        results = [
            _make_analysis("docs/guide.md", matched_shadows=["src/a.py", "src/b.py"]),
        ]
        sc = build_scorecard(config, results)
        assert sc.coverage_pct == 100.0

    def test_partial_coverage(self, temp_dir):
        """One of two source files covered → 50%."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_shadow(temp_dir, "src/b.py")
        _write_source(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/b.py")

        results = [
            _make_analysis("docs/guide.md", matched_shadows=["src/a.py"]),
        ]
        sc = build_scorecard(config, results)
        assert sc.coverage_pct == 50.0

    def test_zero_coverage(self, temp_dir):
        """No docs match any sources → 0%."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py")

        results = [
            _make_analysis("docs/guide.md", matched_shadows=[]),
        ]
        sc = build_scorecard(config, results)
        assert sc.coverage_pct == 0.0

    def test_no_source_files(self, temp_dir):
        """No source files in shadow inventory → 0% (no division error)."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sc = build_scorecard(config, [])
        assert sc.coverage_pct == 0.0
        assert sc.coverage_entries == []

    def test_debris_excluded_from_coverage(self, temp_dir):
        """Debris docs don't contribute to coverage."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py")

        results = [
            _make_analysis("docs/old.md", is_process_artifact=True, matched_shadows=["src/a.py"]),
        ]
        sc = build_scorecard(config, results)
        assert sc.coverage_pct == 0.0

    def test_coverage_by_diataxis_type(self, temp_dir):
        """Coverage grouped by Diataxis classification."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py")

        results = [
            _make_analysis("docs/guide.md", classification="tutorial", matched_shadows=["src/a.py"]),
            _make_analysis("docs/api.md", classification="reference", matched_shadows=[]),
            _make_analysis("docs/api2.md", classification="reference", matched_shadows=["src/a.py"]),
        ]
        sc = build_scorecard(config, results)
        assert sc.coverage_by_type["tutorial"] == 100.0
        assert sc.coverage_by_type["reference"] == 50.0

    def test_signatures_loaded(self, temp_dir):
        """Topic signatures loaded when available."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py")
        _write_signature(temp_dir, "src/a.py", purpose="Handles auth", topics=["JWT", "OAuth"])

        sc = build_scorecard(config, [])
        assert len(sc.coverage_entries) == 1
        assert sc.coverage_entries[0].topic_signature is not None
        assert "JWT" in sc.coverage_entries[0].topic_signature["topics"]

    def test_missing_signatures_handled(self, temp_dir):
        """Sources without signatures get None."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py")

        sc = build_scorecard(config, [])
        assert sc.coverage_entries[0].topic_signature is None


# --- Dead docs ---

class TestDeadDocs:
    def test_dead_docs_listed(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        results = [
            _make_analysis("docs/old.md", is_process_artifact=True),
            _make_analysis("docs/good.md", classification="reference"),
        ]
        sc = build_scorecard(config, results)
        assert sc.dead_docs == ["docs/old.md"]

    def test_no_dead_docs(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        results = [
            _make_analysis("docs/good.md", classification="reference"),
        ]
        sc = build_scorecard(config, results)
        assert sc.dead_docs == []

    def test_debris_excluded_from_accuracy(self, temp_dir):
        """Debris docs not counted in accuracy denominator."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        results = [
            _make_analysis("docs/old.md", is_process_artifact=True,
                           findings=[_make_finding()]),
            _make_analysis("docs/good.md"),
        ]
        sc = build_scorecard(config, results)
        # Only 1 live doc, 0 accuracy errors from it
        assert sc.live_doc_count == 1
        assert sc.total_accuracy_errors == 0


# --- Accuracy ---

class TestAccuracy:
    def test_accuracy_errors_counted(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        results = [
            _make_analysis("docs/a.md", findings=[
                _make_finding("stale_content", "error"),
                _make_finding("incorrect_content", "error"),
            ]),
            _make_analysis("docs/b.md", findings=[
                _make_finding("stale_content", "error"),
            ]),
        ]
        sc = build_scorecard(config, results)
        assert sc.total_accuracy_errors == 3
        assert sc.live_doc_count == 2
        assert sc.accuracy_errors_per_doc == 1.5
        assert sc.accuracy_by_category == {"stale_content": 2, "incorrect_content": 1}

    def test_warnings_not_counted(self, temp_dir):
        """Only error-severity findings counted."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        results = [
            _make_analysis("docs/a.md", findings=[
                _make_finding("stale_content", "warning"),
            ]),
        ]
        sc = build_scorecard(config, results)
        assert sc.total_accuracy_errors == 0

    def test_zero_docs(self, temp_dir):
        """No live docs → 0 errors per doc (no division error)."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sc = build_scorecard(config, [])
        assert sc.accuracy_errors_per_doc == 0.0


# --- Junk code ---

class TestJunkCode:
    def test_junk_from_phase3_findings(self, temp_dir):
        """Phase 3 code debris findings contribute to junk."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        # 10-line source file
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(10)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "commented_out_code", "line_start": 3, "line_end": 5,
             "severity": "warning", "description": "old code"},
        ])

        sc = build_scorecard(config, [])
        assert sc.junk_item_count == 1
        assert sc.junk_total_lines == 3  # lines 3-5
        assert sc.junk_file_count == 1
        assert "code_debris" in sc.junk_sources

    def test_junk_overlapping_ranges_no_double_count(self, temp_dir):
        """Overlapping line ranges from multiple findings should not double-count."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(20)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "commented_out_code", "line_start": 3, "line_end": 8,
             "severity": "warning", "description": "block 1"},
            {"category": "dead_code", "line_start": 5, "line_end": 10,
             "severity": "warning", "description": "block 2"},
        ])

        sc = build_scorecard(config, [])
        # Merged range: 3-10 = 8 lines, not 6+6=12
        assert sc.junk_total_lines == 8

    def test_junk_denominator_all_source_files(self, temp_dir):
        """Junk fraction denominator includes ALL source files, not just junk files."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_shadow(temp_dir, "src/b.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(100)))
        _write_source(temp_dir, "src/b.py", "\n".join(f"line {i}" for i in range(100)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "dead_code", "line_start": 1, "line_end": 10,
             "severity": "warning", "description": "dead"},
        ])

        sc = build_scorecard(config, [])
        # 10 junk lines / 200 total source lines = 5%
        assert sc.junk_total_source_lines == 200
        assert sc.junk_total_lines == 10
        assert abs(sc.junk_fraction - 0.05) < 0.001

    def test_junk_with_dead_code_phase(self, temp_dir):
        """Phase 4 dead code results folded into junk."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(20)))

        dead_code = [
            DeadCodeVerification(
                source_path="src/a.py", name="old_func", kind="function",
                line_start=5, line_end=10, is_dead=True, confidence=0.9,
                reason="unused", remediation="remove",
            ),
        ]
        sc = build_scorecard(config, [], dead_code_results=dead_code)
        assert sc.junk_total_lines == 6  # lines 5-10
        assert "dead_symbol" in sc.junk_sources

    def test_junk_with_dead_plumbing_phase(self, temp_dir):
        """Phase 5 plumbing results folded into junk."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/schema.ts")
        _write_source(temp_dir, "src/schema.ts", "\n".join(f"line {i}" for i in range(20)))

        plumbing = PlumbingResult(
            verifications=[
                PlumbingVerification(
                    source_path="src/schema.ts", field_name="taskTimeoutMs",
                    schema_name="Schema", line_start=5, line_end=5,
                    is_actuated=False, confidence=0.9,
                    trace="not enforced", remediation="add timer",
                ),
            ],
            total_obligations=3,
        )
        sc = build_scorecard(config, [], plumbing_result=plumbing)
        assert sc.junk_total_lines == 1
        assert "unactuated_config" in sc.junk_sources

    def test_junk_without_optional_phases(self, temp_dir):
        """Without Phase 4/5, only Phase 3 contributes; dead_symbol absent from sources."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(10)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "commented_out_code", "line_start": 1, "line_end": 2,
             "severity": "warning", "description": "old"},
        ])

        sc = build_scorecard(config, [], dead_code_results=None, plumbing_result=None)
        assert "dead_symbol" not in sc.junk_sources
        assert "unactuated_config" not in sc.junk_sources
        assert sc.junk_sources == ["code_debris"]

    def test_junk_by_category(self, temp_dir):
        """Item counts and line counts correct per category."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(30)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "commented_out_code", "line_start": 1, "line_end": 5,
             "severity": "warning", "description": "comment block"},
            {"category": "dead_code", "line_start": 10, "line_end": 15,
             "severity": "warning", "description": "dead func"},
        ])

        sc = build_scorecard(config, [])
        assert sc.junk_by_category["commented_out_code"] == 1
        assert sc.junk_by_category["dead_code"] == 1
        assert sc.junk_by_category_lines["commented_out_code"] == 5
        assert sc.junk_by_category_lines["dead_code"] == 6

    def test_junk_worst_files_sorted(self, temp_dir):
        """Junk entries sorted by fraction descending."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # File A: 50% junk
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(10)))
        _write_findings(temp_dir, "src/a.py", [
            {"category": "dead_code", "line_start": 1, "line_end": 5,
             "severity": "warning", "description": "dead"},
        ])
        # File B: 10% junk
        _write_shadow(temp_dir, "src/b.py")
        _write_source(temp_dir, "src/b.py", "\n".join(f"line {i}" for i in range(100)))
        _write_findings(temp_dir, "src/b.py", [
            {"category": "dead_code", "line_start": 1, "line_end": 10,
             "severity": "warning", "description": "dead"},
        ])

        sc = build_scorecard(config, [])
        assert len(sc.junk_entries) == 2
        # First entry should have highest junk fraction
        assert sc.junk_entries[0].junk_fraction > sc.junk_entries[1].junk_fraction


# --- Enforcement ---

class TestEnforcement:
    def test_enforcement_with_plumbing(self, temp_dir):
        """Correct total/unactuated/pct when plumbing is provided."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        plumbing = PlumbingResult(
            verifications=[
                PlumbingVerification(
                    source_path="src/schema.ts", field_name="taskTimeoutMs",
                    schema_name="Schema", line_start=5, line_end=5,
                    is_actuated=False, confidence=0.9,
                    trace="not enforced", remediation="add timer",
                ),
            ],
            total_obligations=4,
        )
        sc = build_scorecard(config, [], plumbing_result=plumbing)
        assert sc.enforcement_total_obligations == 4
        assert sc.enforcement_unactuated == 1
        assert sc.enforcement_pct_unactuated == 25.0

    def test_enforcement_without_plumbing(self, temp_dir):
        """All enforcement fields None when plumbing not run."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sc = build_scorecard(config, [], plumbing_result=None)
        assert sc.enforcement_total_obligations is None
        assert sc.enforcement_unactuated is None
        assert sc.enforcement_pct_unactuated is None
        assert sc.enforcement_by_schema is None

    def test_enforcement_by_schema_grouping(self, temp_dir):
        """Unactuated fields grouped by schema."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        plumbing = PlumbingResult(
            verifications=[
                PlumbingVerification(
                    source_path="src/schema.ts", field_name="taskTimeoutMs",
                    schema_name="TrialSettings", line_start=5, line_end=5,
                    is_actuated=False, confidence=0.9,
                    trace="not enforced", remediation="add timer",
                ),
                PlumbingVerification(
                    source_path="src/schema.ts", field_name="maxRetries",
                    schema_name="TrialSettings", line_start=6, line_end=6,
                    is_actuated=False, confidence=0.85,
                    trace="not enforced", remediation="add retry logic",
                ),
                PlumbingVerification(
                    source_path="src/other.ts", field_name="rateLimit",
                    schema_name="ApiConfig", line_start=10, line_end=10,
                    is_actuated=False, confidence=0.8,
                    trace="not enforced", remediation="add rate limiter",
                ),
            ],
            total_obligations=10,
        )
        sc = build_scorecard(config, [], plumbing_result=plumbing)
        assert "src/schema.ts:TrialSettings" in sc.enforcement_by_schema
        assert "src/other.ts:ApiConfig" in sc.enforcement_by_schema
        ts = sc.enforcement_by_schema["src/schema.ts:TrialSettings"]
        assert ts["unactuated"] == 2
        assert set(ts["fields"]) == {"taskTimeoutMs", "maxRetries"}

    def test_enforcement_zero_unactuated(self, temp_dir):
        """Zero unactuated obligations: zeros not None."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        plumbing = PlumbingResult(
            verifications=[],
            total_obligations=5,
        )
        sc = build_scorecard(config, [], plumbing_result=plumbing)
        assert sc.enforcement_total_obligations == 5
        assert sc.enforcement_unactuated == 0
        assert sc.enforcement_pct_unactuated == 0.0
        assert sc.enforcement_by_schema == {}


# --- Junk results (unified) ---

class TestJunkResults:
    def test_junk_via_junk_results_dict(self, temp_dir):
        """junk_results dict feeds into junk aggregation."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(20)))

        junk_results = {
            "dead_code": JunkAnalysisResult(
                findings=[
                    JunkFinding(
                        source_path="src/a.py", name="old_func", kind="function",
                        category="dead_symbol", line_start=5, line_end=10,
                        confidence=0.9, reason="unused", remediation="remove",
                        original_purpose="function `old_func`",
                    ),
                ],
                total_candidates=3,
                analyzer_name="dead_code",
            ),
        }
        sc = build_scorecard(config, [], junk_results=junk_results)
        assert sc.junk_total_lines == 6  # lines 5-10
        assert "dead_code" in sc.junk_sources

    def test_junk_results_with_plumbing(self, temp_dir):
        """junk_results with dead_plumbing populates enforcement metrics."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/schema.ts")
        _write_source(temp_dir, "src/schema.ts", "\n".join(f"line {i}" for i in range(20)))

        junk_results = {
            "dead_plumbing": JunkAnalysisResult(
                findings=[
                    JunkFinding(
                        source_path="src/schema.ts", name="taskTimeoutMs",
                        kind="config_field", category="unactuated_config",
                        line_start=5, line_end=5, confidence=0.9,
                        reason="not enforced", remediation="add timer",
                        original_purpose="field `taskTimeoutMs` in `Schema`",
                        metadata={"schema_name": "Schema", "trace": "not enforced"},
                    ),
                ],
                total_candidates=3,
                analyzer_name="dead_plumbing",
            ),
        }
        sc = build_scorecard(config, [], junk_results=junk_results)
        assert sc.enforcement_total_obligations == 3
        assert sc.enforcement_unactuated == 1
        assert "dead_plumbing" in sc.junk_sources

    def test_junk_results_enforcement_by_schema(self, temp_dir):
        """Enforcement by schema groups correctly from junk_results."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        junk_results = {
            "dead_plumbing": JunkAnalysisResult(
                findings=[
                    JunkFinding(
                        source_path="src/schema.ts", name="taskTimeoutMs",
                        kind="config_field", category="unactuated_config",
                        line_start=5, line_end=5, confidence=0.9,
                        reason="not enforced", remediation="add timer",
                        original_purpose="field `taskTimeoutMs` in `TrialSettings`",
                        metadata={"schema_name": "TrialSettings", "trace": "not enforced"},
                    ),
                    JunkFinding(
                        source_path="src/schema.ts", name="maxRetries",
                        kind="config_field", category="unactuated_config",
                        line_start=6, line_end=6, confidence=0.85,
                        reason="not enforced", remediation="add retry logic",
                        original_purpose="field `maxRetries` in `TrialSettings`",
                        metadata={"schema_name": "TrialSettings", "trace": "not enforced"},
                    ),
                ],
                total_candidates=5,
                analyzer_name="dead_plumbing",
            ),
        }
        sc = build_scorecard(config, [], junk_results=junk_results)
        assert "src/schema.ts:TrialSettings" in sc.enforcement_by_schema
        ts = sc.enforcement_by_schema["src/schema.ts:TrialSettings"]
        assert ts["unactuated"] == 2
        assert set(ts["fields"]) == {"taskTimeoutMs", "maxRetries"}

    def test_backward_compat_old_params_still_work(self, temp_dir):
        """Old dead_code_results and plumbing_result params still work."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(20)))

        dead_code = [
            DeadCodeVerification(
                source_path="src/a.py", name="old_func", kind="function",
                line_start=5, line_end=10, is_dead=True, confidence=0.9,
                reason="unused", remediation="remove",
            ),
        ]
        sc = build_scorecard(config, [], dead_code_results=dead_code)
        assert sc.junk_total_lines == 6
        assert "dead_symbol" in sc.junk_sources

    def test_junk_results_takes_precedence_over_old_params(self, temp_dir):
        """When both junk_results and old params provided, junk_results wins."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_shadow(temp_dir, "src/a.py")
        _write_source(temp_dir, "src/a.py", "\n".join(f"line {i}" for i in range(20)))

        junk_results = {
            "dead_code": JunkAnalysisResult(
                findings=[
                    JunkFinding(
                        source_path="src/a.py", name="new_finding", kind="function",
                        category="dead_symbol", line_start=1, line_end=2,
                        confidence=0.95, reason="unused new", remediation="remove",
                        original_purpose="function `new_finding`",
                    ),
                ],
                total_candidates=1,
                analyzer_name="dead_code",
            ),
        }
        old_dead_code = [
            DeadCodeVerification(
                source_path="src/a.py", name="old_finding", kind="function",
                line_start=5, line_end=10, is_dead=True, confidence=0.9,
                reason="unused old", remediation="remove",
            ),
        ]
        # Pass both — junk_results should take precedence
        sc = build_scorecard(config, [], junk_results=junk_results, dead_code_results=old_dead_code)
        # Should only have 2 lines (from junk_results), not 6 (from old params)
        assert sc.junk_total_lines == 2
        # dead_symbol should appear only once in sources
        assert sc.junk_sources.count("dead_code") == 1


# --- Empty audit ---

class TestEmptyAudit:
    def test_empty_produces_valid_scorecard(self, temp_dir):
        """Empty audit produces a valid zero scorecard."""
        config = Config(root_path=temp_dir, respect_gitignore=False)
        sc = build_scorecard(config, [])
        assert sc.coverage_pct == 0.0
        assert sc.dead_docs == []
        assert sc.total_accuracy_errors == 0
        assert sc.accuracy_errors_per_doc == 0.0
        assert sc.junk_total_lines == 0
        assert sc.junk_fraction == 0.0
        assert sc.enforcement_total_obligations is None
