"""Tests for lightweight staleness marking (inject warnings + manifest)."""

import json
from pathlib import Path

import pytest

from osoji.config import Config, SHADOW_DIR
from osoji.hasher import compute_file_hash, compute_impl_hash, extract_source_hash
from osoji.shadow import (
    STALE_WARNING_SOURCE,
    STALE_WARNING_IMPL,
    _STALE_WARNINGS,
    assemble_shadow_doc,
    assemble_directory_shadow_doc,
    _extract_body_from_shadow,
    strip_stale_warnings,
    inject_stale_warning,
    mark_stale_docs,
)


# ---------------------------------------------------------------------------
# Warning constant sanity checks
# ---------------------------------------------------------------------------

class TestWarningConstants:
    def test_source_warning_does_not_start_with_at(self):
        assert not STALE_WARNING_SOURCE.startswith("@")

    def test_impl_warning_does_not_start_with_at(self):
        assert not STALE_WARNING_IMPL.startswith("@")

    def test_warnings_are_single_line(self):
        assert "\n" not in STALE_WARNING_SOURCE
        assert "\n" not in STALE_WARNING_IMPL

    def test_set_contains_both(self):
        assert _STALE_WARNINGS == {STALE_WARNING_SOURCE, STALE_WARNING_IMPL}


# ---------------------------------------------------------------------------
# strip_stale_warnings
# ---------------------------------------------------------------------------

class TestStripStaleWarnings:
    def test_removes_source_warning(self):
        text = f"some text\n{STALE_WARNING_SOURCE}\nmore text"
        assert strip_stale_warnings(text) == "some text\nmore text"

    def test_removes_impl_warning(self):
        text = f"some text\n{STALE_WARNING_IMPL}\nmore text"
        assert strip_stale_warnings(text) == "some text\nmore text"

    def test_removes_both_warnings(self):
        text = f"{STALE_WARNING_SOURCE}\n{STALE_WARNING_IMPL}\nbody"
        assert strip_stale_warnings(text) == "body"

    def test_preserves_other_content(self):
        text = "line one\nline two\nline three"
        assert strip_stale_warnings(text) == text

    def test_empty_string(self):
        assert strip_stale_warnings("") == ""


# ---------------------------------------------------------------------------
# inject_stale_warning
# ---------------------------------------------------------------------------

def _make_shadow(tmp_path: Path, content: str) -> Path:
    shadow = tmp_path / "test.shadow.md"
    shadow.write_text(content, encoding="utf-8")
    return shadow


class TestInjectStaleWarning:
    def test_injects_source_warning(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        count = inject_stale_warning(shadow, "stale")
        assert count == 1
        result = shadow.read_text(encoding="utf-8")
        assert STALE_WARNING_SOURCE in result
        assert STALE_WARNING_IMPL not in result

    def test_injects_impl_warning(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        count = inject_stale_warning(shadow, "stale-impl")
        assert count == 1
        result = shadow.read_text(encoding="utf-8")
        assert STALE_WARNING_IMPL in result
        assert STALE_WARNING_SOURCE not in result

    def test_idempotent(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        inject_stale_warning(shadow, "stale")
        count = inject_stale_warning(shadow, "stale")
        assert count == 0
        result = shadow.read_text(encoding="utf-8")
        assert result.count(STALE_WARNING_SOURCE) == 1

    def test_both_warnings_injected(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        inject_stale_warning(shadow, "stale")
        inject_stale_warning(shadow, "stale-impl")
        result = shadow.read_text(encoding="utf-8")
        assert STALE_WARNING_SOURCE in result
        assert STALE_WARNING_IMPL in result

    def test_does_not_break_hash_extraction(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc123\n@impl-hash: def456\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        inject_stale_warning(shadow, "stale")
        inject_stale_warning(shadow, "stale-impl")
        result = shadow.read_text(encoding="utf-8")
        assert extract_source_hash(result) == "abc123"

    def test_unknown_reason_returns_zero(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody"
        shadow = _make_shadow(tmp_path, doc)
        assert inject_stale_warning(shadow, "missing") == 0

    def test_warning_placed_after_header(self, tmp_path):
        doc = "# foo.py\n@source-hash: abc\n@impl-hash: def\n@generated: 2024-01-01\n\nbody text"
        shadow = _make_shadow(tmp_path, doc)
        inject_stale_warning(shadow, "stale")
        lines = shadow.read_text(encoding="utf-8").split("\n")
        # Header blank line is at index 4, warning should be at index 5
        assert lines[4] == ""
        assert lines[5] == STALE_WARNING_SOURCE
        assert lines[6] == "body text"


# ---------------------------------------------------------------------------
# assemble_shadow_doc strips warnings
# ---------------------------------------------------------------------------

class TestAssembleStripsWarnings:
    def test_assemble_shadow_doc_strips_warnings(self):
        body = f"{STALE_WARNING_SOURCE}\nactual body"
        compute_impl_hash.cache_clear()
        doc = assemble_shadow_doc(Path("foo.py"), "hash123", body)
        assert STALE_WARNING_SOURCE not in doc
        assert "actual body" in doc

    def test_assemble_directory_shadow_doc_strips_warnings(self):
        body = f"{STALE_WARNING_IMPL}\ndir summary"
        compute_impl_hash.cache_clear()
        doc = assemble_directory_shadow_doc(Path("src"), "hash123", body)
        assert STALE_WARNING_IMPL not in doc
        assert "dir summary" in doc


# ---------------------------------------------------------------------------
# _extract_body_from_shadow strips warnings
# ---------------------------------------------------------------------------

class TestExtractBodyStripsWarnings:
    def test_strips_source_warning(self):
        doc = f"# foo.py\n@source-hash: abc\n@generated: 2024-01-01\n\n{STALE_WARNING_SOURCE}\nbody"
        body = _extract_body_from_shadow(doc)
        assert STALE_WARNING_SOURCE not in body
        assert "body" in body

    def test_strips_both_warnings(self):
        doc = f"# foo.py\n@source-hash: abc\n@generated: 2024-01-01\n\n{STALE_WARNING_SOURCE}\n{STALE_WARNING_IMPL}\nbody"
        body = _extract_body_from_shadow(doc)
        assert STALE_WARNING_SOURCE not in body
        assert STALE_WARNING_IMPL not in body
        assert "body" in body


# ---------------------------------------------------------------------------
# mark_stale_docs
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    """Create a minimal project with source files and shadow docs."""
    src = tmp_path / "hello.py"
    src.write_text("print('hello')", encoding="utf-8")

    src2 = tmp_path / "world.py"
    src2.write_text("print('world')", encoding="utf-8")

    shadow_dir = tmp_path / ".osoji" / "shadow"
    shadow_dir.mkdir(parents=True)

    return tmp_path


class TestMarkStaleDocs:
    def test_marks_stale_files(self, project):
        root = project
        src = root / "hello.py"
        config = Config(root_path=root)

        # Write a shadow doc with wrong source hash → stale
        compute_impl_hash.cache_clear()
        impl_hash = compute_impl_hash()
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: oldhash\n@impl-hash: {impl_hash}\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        result = mark_stale_docs(config)
        assert len(result.stale_files) >= 1
        assert result.marked_count >= 1

        content = shadow_path.read_text(encoding="utf-8")
        assert STALE_WARNING_SOURCE in content

    def test_marks_stale_impl_files(self, project):
        root = project
        src = root / "hello.py"
        config = Config(root_path=root)

        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: {source_hash}\n@impl-hash: wronghash!!\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        result = mark_stale_docs(config)
        # hello.py should be stale-impl, world.py should be missing
        stale_impl = [(p, r) for p, r in result.stale_files if r == "stale-impl"]
        assert len(stale_impl) >= 1

        content = shadow_path.read_text(encoding="utf-8")
        assert STALE_WARNING_IMPL in content

    def test_skips_missing_files(self, project):
        root = project
        config = Config(root_path=root)

        # No shadow docs at all → all "missing", none can be marked
        result = mark_stale_docs(config)
        missing = [(p, r) for p, r in result.stale_files if r == "missing"]
        assert len(missing) >= 2
        assert result.marked_count == 0

    def test_writes_manifest(self, project):
        root = project
        config = Config(root_path=root)

        mark_stale_docs(config)

        assert config.staleness_manifest_path.exists()
        manifest = json.loads(config.staleness_manifest_path.read_text(encoding="utf-8"))
        assert "generated" in manifest
        assert "stale" in manifest
        assert isinstance(manifest["stale"], list)

    def test_manifest_entries_have_path_and_reason(self, project):
        root = project
        config = Config(root_path=root)

        mark_stale_docs(config)

        manifest = json.loads(config.staleness_manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["stale"]:
            assert "path" in entry
            assert "reason" in entry


# ---------------------------------------------------------------------------
# Config.staleness_manifest_path
# ---------------------------------------------------------------------------

class TestConfigStalenessManifestPath:
    def test_resolves_correctly(self, tmp_path):
        config = Config(root_path=tmp_path)
        expected = tmp_path / ".osoji" / "staleness.json"
        assert config.staleness_manifest_path == expected
