"""Tests for hasher utilities — impl hash auto-discovery and findings validation."""

from pathlib import Path

from osoji.hasher import (
    _IMPL_HASH_EXCLUDES,
    compute_file_hash,
    compute_impl_hash,
    is_findings_current,
)


class TestComputeImplHash:
    def test_returns_hex_string(self):
        h = compute_impl_hash()
        assert isinstance(h, str)
        assert len(h) == 16
        # Must be valid hex
        int(h, 16)

    def test_auto_discovers_py_files(self):
        """impl hash should include more files than the old 8-file whitelist."""
        pkg_dir = Path(__file__).resolve().parent.parent / "src" / "osoji"
        all_py = sorted(pkg_dir.rglob("*.py"))
        included = [
            f for f in all_py
            if f.relative_to(pkg_dir).as_posix() not in _IMPL_HASH_EXCLUDES
        ]
        # Old whitelist had 8 files; auto-discovery should find many more
        assert len(included) > 8

    def test_excludes_are_respected(self):
        """Excluded file entries in _IMPL_HASH_EXCLUDES point to real files (guards against stale excludes)."""
        pkg_dir = Path(__file__).resolve().parent.parent / "src" / "osoji"
        for excluded in _IMPL_HASH_EXCLUDES:
            excluded_path = pkg_dir / excluded
            if excluded_path.exists():
                assert excluded_path.is_file()

    def test_deterministic(self):
        """Same process should return the same hash (cached)."""
        h1 = compute_impl_hash()
        h2 = compute_impl_hash()
        assert h1 == h2


class TestIsFindingsCurrent:
    def test_matching_hashes(self, temp_dir):
        """Current findings with matching hashes return True."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        source_hash = compute_file_hash(source)
        impl_hash = compute_impl_hash()
        assert is_findings_current(source_hash, impl_hash, source) is True

    def test_mismatched_source_hash(self, temp_dir):
        """Changed source file → stale."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        source_hash = compute_file_hash(source)
        impl_hash = compute_impl_hash()
        # Change the source
        source.write_text("print('world')\n")
        assert is_findings_current(source_hash, impl_hash, source) is False

    def test_mismatched_impl_hash(self, temp_dir):
        """Wrong impl hash → stale."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        source_hash = compute_file_hash(source)
        assert is_findings_current(source_hash, "bad_impl_hash", source) is False

    def test_none_source_hash(self, temp_dir):
        """None source hash → stale."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        assert is_findings_current(None, compute_impl_hash(), source) is False

    def test_none_impl_hash(self, temp_dir):
        """None impl hash → stale."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        source_hash = compute_file_hash(source)
        assert is_findings_current(source_hash, None, source) is False

    def test_both_none(self, temp_dir):
        """Both None → stale."""
        source = temp_dir / "test.py"
        source.write_text("print('hello')\n")
        assert is_findings_current(None, None, source) is False

    def test_missing_source_file(self, temp_dir):
        """Source file doesn't exist → stale."""
        source = temp_dir / "missing.py"
        assert is_findings_current("some_hash", compute_impl_hash(), source) is False
