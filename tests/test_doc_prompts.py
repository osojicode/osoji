"""Tests for the doc_prompts module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from osoji.doc_prompts import (
    Concept,
    DocPromptsResult,
    WritingPrompt,
    _compute_priority,
    _map_coverage,
    _compute_coverage_summary,
    _cluster_for_prompts,
    _FileMetadata,
    _format_file_listing,
)
from osoji.scorecard import CoverageEntry, Scorecard


def _make_scorecard(**kwargs) -> Scorecard:
    """Create a minimal Scorecard for testing."""
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
    defaults.update(kwargs)
    return Scorecard(**defaults)


def _make_concept(**kwargs) -> Concept:
    """Create a Concept with sensible defaults."""
    defaults = dict(
        concept_id="test-concept",
        concept_name="Test Concept",
        concept_description="A test concept",
        source_files=["src/foo.py"],
        concept_role="public_api",
        appropriate_types=["reference", "tutorial", "how-to"],
        appropriateness_rationale="Public API needs reference, tutorial, and how-to",
        fan_in=0,
        public_count=0,
    )
    defaults.update(kwargs)
    return Concept(**defaults)


# ---------------------------------------------------------------------------
# Priority scoring tests
# ---------------------------------------------------------------------------

class TestComputePriority:

    def test_public_api_high_fanin_is_high(self):
        c = _make_concept(concept_role="public_api", fan_in=6, public_count=5)
        _compute_priority(c)
        assert c.priority == "high"
        assert c.priority_score >= 6

    def test_internal_utility_is_low(self):
        c = _make_concept(
            concept_role="internal_utility",
            fan_in=0,
            public_count=0,
            appropriate_types=["reference"],
        )
        c.coverage_status = "fully_documented"
        _compute_priority(c)
        assert c.priority == "low"
        assert c.priority_score < 3

    def test_cli_command_moderate_fanin_is_medium(self):
        c = _make_concept(concept_role="cli_command", fan_in=3, public_count=0)
        c.coverage_status = "partially_documented"  # avoid +2 from undocumented
        _compute_priority(c)
        assert c.priority == "medium"

    def test_testing_infra_penalty(self):
        c = _make_concept(
            concept_role="testing_infrastructure",
            fan_in=0,
            public_count=0,
        )
        _compute_priority(c)
        assert c.priority == "low"
        assert c.priority_score < 0

    def test_undocumented_bonus(self):
        c = _make_concept(
            concept_role="data_model",
            fan_in=0,
            public_count=0,
        )
        c.coverage_status = "undocumented"
        _compute_priority(c)
        score_undoc = c.priority_score

        c2 = _make_concept(
            concept_role="data_model",
            fan_in=0,
            public_count=0,
        )
        c2.coverage_status = "fully_documented"
        _compute_priority(c2)
        assert score_undoc > c2.priority_score

    def test_priority_signals_populated(self):
        c = _make_concept(
            concept_role="public_api",
            fan_in=6,
            public_count=3,
        )
        c.coverage_status = "undocumented"
        _compute_priority(c)
        assert len(c.priority_signals) > 0
        assert any("user-facing" in s for s in c.priority_signals)
        assert any("fan-in" in s for s in c.priority_signals)


# ---------------------------------------------------------------------------
# Coverage mapping tests
# ---------------------------------------------------------------------------

class TestMapCoverage:

    def test_concept_with_reference_needing_tutorial_and_howto(self):
        c = _make_concept(
            concept_id="auth",
            source_files=["src/auth.py"],
            appropriate_types=["reference", "tutorial", "how-to"],
        )
        scorecard = _make_scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path="src/auth.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/api.md", "classification": "reference"}],
                ),
            ],
        )
        _map_coverage([c], scorecard)
        assert c.coverage_status == "partially_documented"
        assert set(c.missing_types) == {"tutorial", "how-to"}
        assert len(c.existing_coverage) == 1
        assert c.existing_coverage[0]["diataxis_type"] == "reference"

    def test_fully_documented_concept(self):
        c = _make_concept(
            source_files=["src/foo.py"],
            appropriate_types=["reference"],
        )
        scorecard = _make_scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path="src/foo.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/ref.md", "classification": "reference"}],
                ),
            ],
        )
        _map_coverage([c], scorecard)
        assert c.coverage_status == "fully_documented"
        assert c.missing_types == []

    def test_undocumented_concept(self):
        c = _make_concept(
            source_files=["src/bar.py"],
            appropriate_types=["reference", "tutorial"],
        )
        scorecard = _make_scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path="src/bar.py",
                    topic_signature=None,
                    covering_docs=[],
                ),
            ],
        )
        _map_coverage([c], scorecard)
        assert c.coverage_status == "undocumented"
        assert set(c.missing_types) == {"reference", "tutorial"}

    def test_multi_file_concept_coverage(self):
        """A concept spanning multiple source files with docs covering different files."""
        c = _make_concept(
            source_files=["src/a.py", "src/b.py"],
            appropriate_types=["reference", "tutorial"],
        )
        scorecard = _make_scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path="src/a.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/ref.md", "classification": "reference"}],
                ),
                CoverageEntry(
                    source_path="src/b.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/tut.md", "classification": "tutorial"}],
                ),
            ],
        )
        _map_coverage([c], scorecard)
        assert c.coverage_status == "fully_documented"
        assert len(c.existing_coverage) == 2

    def test_deduplication(self):
        """Same doc covering same concept via different source files shouldn't duplicate."""
        c = _make_concept(
            source_files=["src/a.py", "src/b.py"],
            appropriate_types=["reference"],
        )
        scorecard = _make_scorecard(
            coverage_entries=[
                CoverageEntry(
                    source_path="src/a.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/ref.md", "classification": "reference"}],
                ),
                CoverageEntry(
                    source_path="src/b.py",
                    topic_signature=None,
                    covering_docs=[{"path": "docs/ref.md", "classification": "reference"}],
                ),
            ],
        )
        _map_coverage([c], scorecard)
        assert len(c.existing_coverage) == 1


# ---------------------------------------------------------------------------
# Coverage summary tests
# ---------------------------------------------------------------------------

class TestComputeCoverageSummary:

    def test_basic_summary(self):
        concepts = [
            _make_concept(
                concept_id="a",
                appropriate_types=["reference", "tutorial"],
                existing_coverage=[{"diataxis_type": "reference", "doc_path": "r.md"}],
            ),
            _make_concept(
                concept_id="b",
                appropriate_types=["reference"],
                existing_coverage=[],
            ),
        ]
        # Manually set coverage lists since _make_concept doesn't set existing_coverage in field
        concepts[0].existing_coverage = [{"diataxis_type": "reference", "doc_path": "r.md"}]
        concepts[1].existing_coverage = []

        result = _compute_coverage_summary(concepts)
        assert result["reference"]["needed"] == 2
        assert result["reference"]["covered"] == 1
        assert result["tutorial"]["needed"] == 1
        assert result["tutorial"]["covered"] == 0


# ---------------------------------------------------------------------------
# Clustering tests
# ---------------------------------------------------------------------------

class TestClusterForPrompts:

    def test_concepts_sharing_source_files_cluster(self):
        c1 = _make_concept(
            concept_id="a",
            source_files=["src/x.py", "src/y.py", "src/z.py"],
            appropriate_types=["reference", "tutorial"],
        )
        c1.missing_types = ["tutorial"]

        c2 = _make_concept(
            concept_id="b",
            source_files=["src/x.py", "src/y.py"],
            appropriate_types=["reference", "tutorial"],
        )
        c2.missing_types = ["tutorial"]

        clusters = _cluster_for_prompts([c1, c2])
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_no_cluster_without_overlap(self):
        c1 = _make_concept(
            concept_id="a",
            source_files=["src/x.py"],
        )
        c1.missing_types = ["tutorial"]

        c2 = _make_concept(
            concept_id="b",
            source_files=["src/y.py"],
        )
        c2.missing_types = ["tutorial"]

        clusters = _cluster_for_prompts([c1, c2])
        assert len(clusters) == 0

    def test_no_cluster_without_shared_missing_type(self):
        c1 = _make_concept(
            concept_id="a",
            source_files=["src/x.py", "src/y.py"],
        )
        c1.missing_types = ["tutorial"]

        c2 = _make_concept(
            concept_id="b",
            source_files=["src/x.py", "src/y.py"],
        )
        c2.missing_types = ["reference"]  # different missing type

        clusters = _cluster_for_prompts([c1, c2])
        assert len(clusters) == 0

    def test_fully_documented_not_clustered(self):
        c1 = _make_concept(concept_id="a", source_files=["src/x.py"])
        c1.missing_types = []  # fully documented
        clusters = _cluster_for_prompts([c1])
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# Format file listing test
# ---------------------------------------------------------------------------

class TestFormatFileListing:

    def test_basic_format(self):
        metadata = [
            _FileMetadata(
                path="src/foo.py",
                purpose="Does foo things",
                topics=["foo", "bar"],
                file_role="service",
                public_count=3,
                fan_in=5,
            ),
        ]
        result = _format_file_listing(metadata)
        assert "src/foo.py" in result
        assert "Does foo things" in result
        assert "public_count: 3" in result
        assert "fan_in: 5" in result


# ---------------------------------------------------------------------------
# DocPromptsResult tests
# ---------------------------------------------------------------------------

class TestDocPromptsResult:

    def test_empty_result(self):
        r = DocPromptsResult(concepts=[], writing_prompts=[])
        assert r.total_concepts == 0
        assert r.total_prompts == 0
        assert r.total_gaps == 0

    def test_serialization_roundtrip(self):
        """Test that the result can be serialized and deserialized back."""
        from osoji.audit import _serialize_doc_prompts, _deserialize_doc_prompts

        c = _make_concept(concept_id="test", missing_types=["tutorial"])
        _compute_priority(c)
        p = WritingPrompt(
            prompt_id="test-tutorial",
            target_concepts=["test"],
            diataxis_type="tutorial",
            priority="high",
            prompt_text="Write a tutorial...",
        )
        result = DocPromptsResult(
            concepts=[c],
            writing_prompts=[p],
            total_concepts=1,
            fully_documented=0,
            partially_documented=0,
            undocumented=1,
            coverage_by_type={"tutorial": {"needed": 1, "covered": 0}},
            total_gaps=1,
            total_prompts=1,
        )
        serialized = _serialize_doc_prompts(result)
        assert serialized["coverage_summary"]["total_concepts"] == 1
        assert serialized["coverage_summary"]["total_gaps"] == 1
        assert serialized["coverage_summary"]["total_prompts"] == 1
        assert len(serialized["concept_inventory"]) == 1
        assert len(serialized["writing_prompts"]) == 1
        assert serialized["concept_inventory"][0]["concept_id"] == "test"
        assert serialized["writing_prompts"][0]["prompt_id"] == "test-tutorial"

        # Deserialize and verify roundtrip
        deserialized = _deserialize_doc_prompts(serialized)
        assert deserialized.total_concepts == 1
        assert deserialized.total_gaps == 1
        assert deserialized.total_prompts == 1
        assert deserialized.fully_documented == 0
        assert deserialized.undocumented == 1
        assert len(deserialized.concepts) == 1
        assert deserialized.concepts[0].concept_id == "test"
        assert deserialized.concepts[0].concept_name == "Test Concept"
        assert deserialized.concepts[0].missing_types == ["tutorial"]
        assert deserialized.concepts[0].priority in ("high", "medium", "low")
        assert deserialized.concepts[0].priority_score > 0  # recomputed
        assert len(deserialized.writing_prompts) == 1
        assert deserialized.writing_prompts[0].prompt_id == "test-tutorial"
        assert deserialized.writing_prompts[0].prompt_text == "Write a tutorial..."
        assert deserialized.coverage_by_type == {"tutorial": {"needed": 1, "covered": 0}}
