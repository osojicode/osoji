"""Tests for implementation hash staleness detection."""

import re
from pathlib import Path

import pytest

from osoji.hasher import compute_impl_hash, extract_impl_hash, _IMPL_HASH_SOURCES
from osoji.shadow import (
    assemble_shadow_doc,
    assemble_directory_shadow_doc,
    is_stale,
    is_directory_stale,
    staleness_reason,
)
from osoji.config import Config


# ---------------------------------------------------------------------------
# compute_impl_hash
# ---------------------------------------------------------------------------

class TestComputeImplHash:
    def test_returns_16_char_hex(self):
        compute_impl_hash.cache_clear()
        h = compute_impl_hash()
        assert isinstance(h, str)
        assert len(h) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", h)

    def test_is_deterministic(self):
        compute_impl_hash.cache_clear()
        h1 = compute_impl_hash()
        compute_impl_hash.cache_clear()
        h2 = compute_impl_hash()
        assert h1 == h2

    def test_impl_hash_sources_are_sorted(self):
        assert _IMPL_HASH_SOURCES == tuple(sorted(_IMPL_HASH_SOURCES))


# ---------------------------------------------------------------------------
# extract_impl_hash
# ---------------------------------------------------------------------------

class TestExtractImplHash:
    def test_extracts_from_header(self):
        doc = "# foo.py\n@source-hash: abc123\n@impl-hash: deadbeef01234567\n@generated: 2024-01-01\n\nbody"
        assert extract_impl_hash(doc) == "deadbeef01234567"

    def test_returns_none_for_old_format(self):
        doc = "# foo.py\n@source-hash: abc123\n@generated: 2024-01-01\n\nbody"
        assert extract_impl_hash(doc) is None

    def test_returns_none_for_empty(self):
        assert extract_impl_hash("") is None


# ---------------------------------------------------------------------------
# assemble_shadow_doc
# ---------------------------------------------------------------------------

class TestAssembleShadowDoc:
    def test_includes_impl_hash(self):
        compute_impl_hash.cache_clear()
        doc = assemble_shadow_doc(Path("foo.py"), "sourcehash123456", "body text")
        assert "@impl-hash:" in doc
        impl = extract_impl_hash(doc)
        assert impl == compute_impl_hash()

    def test_header_order(self):
        doc = assemble_shadow_doc(Path("foo.py"), "sourcehash123456", "body")
        lines = doc.splitlines()
        assert lines[0].startswith("# ")
        assert lines[1].startswith("@source-hash:")
        assert lines[2].startswith("@impl-hash:")
        assert lines[3].startswith("@generated:")


class TestAssembleDirectoryShadowDoc:
    def test_includes_impl_hash(self):
        compute_impl_hash.cache_clear()
        doc = assemble_directory_shadow_doc(Path("src"), "childrenhash1234", "body text")
        assert "@impl-hash:" in doc
        impl = extract_impl_hash(doc)
        assert impl == compute_impl_hash()

    def test_header_order(self):
        doc = assemble_directory_shadow_doc(Path("src"), "childrenhash1234", "body")
        lines = doc.splitlines()
        assert lines[0].startswith("# ")
        assert lines[1].startswith("@children-hash:")
        assert lines[2].startswith("@impl-hash:")
        assert lines[3].startswith("@generated:")


# ---------------------------------------------------------------------------
# is_stale with impl hash
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    """Create a minimal project with a source file and matching shadow doc."""
    src = tmp_path / "hello.py"
    src.write_text("print('hello')", encoding="utf-8")

    osoji_dir = tmp_path / ".osoji" / "shadow"
    osoji_dir.mkdir(parents=True)

    return tmp_path, src


def _make_config(root: Path, force: bool = False) -> Config:
    return Config(root_path=root, force=force)


class TestIsStaleImplHash:
    def test_stale_when_impl_hash_missing(self, project):
        root, src = project
        config = _make_config(root)

        # Write a shadow doc WITHOUT @impl-hash (old format)
        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: {source_hash}\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert is_stale(config, src) is True

    def test_stale_when_impl_hash_differs(self, project):
        root, src = project
        config = _make_config(root)

        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: {source_hash}\n@impl-hash: wrong_hash_value!\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert is_stale(config, src) is True

    def test_not_stale_when_both_hashes_match(self, project):
        root, src = project
        config = _make_config(root)

        # Use assemble_shadow_doc which embeds both hashes correctly
        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        doc = assemble_shadow_doc(src, source_hash, "body")
        shadow_path.write_text(doc, encoding="utf-8")

        assert is_stale(config, src) is False


# ---------------------------------------------------------------------------
# is_directory_stale with impl hash
# ---------------------------------------------------------------------------

class TestIsDirectoryStaleImplHash:
    def test_stale_when_impl_hash_missing(self, tmp_path):
        config = _make_config(tmp_path)
        dir_path = tmp_path
        shadow_path = config.shadow_path_for_dir(dir_path)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# dir/\n@children-hash: abc123\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert is_directory_stale(config, dir_path, "abc123") is True

    def test_stale_when_impl_hash_differs(self, tmp_path):
        config = _make_config(tmp_path)
        dir_path = tmp_path
        shadow_path = config.shadow_path_for_dir(dir_path)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# dir/\n@children-hash: abc123\n@impl-hash: wronghashvalue!!\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert is_directory_stale(config, dir_path, "abc123") is True

    def test_not_stale_when_all_match(self, tmp_path):
        config = _make_config(tmp_path)
        dir_path = tmp_path
        shadow_path = config.shadow_path_for_dir(dir_path)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        doc = assemble_directory_shadow_doc(dir_path, "abc123", "body")
        shadow_path.write_text(doc, encoding="utf-8")

        assert is_directory_stale(config, dir_path, "abc123") is False


# ---------------------------------------------------------------------------
# staleness_reason
# ---------------------------------------------------------------------------

class TestStalenessReason:
    def test_missing_when_no_shadow(self, project):
        root, src = project
        config = _make_config(root)
        assert staleness_reason(config, src) == "missing"

    def test_stale_when_source_changed(self, project):
        root, src = project
        config = _make_config(root)

        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        compute_impl_hash.cache_clear()
        impl_hash = compute_impl_hash()
        shadow_path.write_text(
            f"# hello.py\n@source-hash: oldhash\n@impl-hash: {impl_hash}\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert staleness_reason(config, src) == "stale"

    def test_stale_impl_when_impl_hash_differs(self, project):
        root, src = project
        config = _make_config(root)

        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: {source_hash}\n@impl-hash: wronghashvalue!!\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert staleness_reason(config, src) == "stale-impl"

    def test_stale_impl_when_impl_hash_missing(self, project):
        root, src = project
        config = _make_config(root)

        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text(
            f"# hello.py\n@source-hash: {source_hash}\n@generated: 2024-01-01\n\nbody",
            encoding="utf-8",
        )

        assert staleness_reason(config, src) == "stale-impl"

    def test_none_when_current(self, project):
        root, src = project
        config = _make_config(root)

        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        doc = assemble_shadow_doc(src, source_hash, "body")
        shadow_path.write_text(doc, encoding="utf-8")

        assert staleness_reason(config, src) is None

    def test_force_returns_stale(self, project):
        root, src = project
        config = _make_config(root, force=True)

        from osoji.hasher import compute_file_hash
        source_hash = compute_file_hash(src)
        shadow_path = config.shadow_path_for(src)
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        doc = assemble_shadow_doc(src, source_hash, "body")
        shadow_path.write_text(doc, encoding="utf-8")

        assert staleness_reason(config, src) == "stale"

    def test_force_missing_returns_missing(self, project):
        root, src = project
        config = _make_config(root, force=True)
        assert staleness_reason(config, src) == "missing"
