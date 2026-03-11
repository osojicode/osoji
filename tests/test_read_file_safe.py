"""Tests for read_file_safe() binary detection and encoding handling."""

from pathlib import Path

from osoji.hasher import read_file_safe


class TestReadFileSafe:
    """Tests for read_file_safe() utility."""

    def test_normal_utf8_file(self, tmp_path: Path):
        f = tmp_path / "hello.py"
        f.write_text("print('hello world')\n", encoding="utf-8")
        content, is_binary = read_file_safe(f)
        assert not is_binary
        assert "hello world" in content

    def test_utf8_bom_file(self, tmp_path: Path):
        """Files with UTF-8 BOM should be read correctly."""
        f = tmp_path / "bom.py"
        f.write_bytes(b"\xef\xbb\xbfprint('bom')\n")
        content, is_binary = read_file_safe(f)
        assert not is_binary
        assert "print('bom')" in content
        # BOM should be stripped by utf-8-sig
        assert not content.startswith("\ufeff")

    def test_binary_with_null_bytes(self, tmp_path: Path):
        """Files with null bytes detected as binary."""
        f = tmp_path / "data.bin"
        f.write_bytes(b"MZ\x00\x00" + b"\x90" * 100)
        content, is_binary = read_file_safe(f)
        assert is_binary
        assert content == ""

    def test_jpeg_detected_as_binary(self, tmp_path: Path):
        """JPEG files (no null bytes in header) detected via non-text ratio."""
        f = tmp_path / "image.jpg"
        # JPEG header: ff d8 ff e0 followed by high-entropy binary data
        data = b"\xff\xd8\xff\xe0" + bytes(range(128, 256)) * 10
        f.write_bytes(data)
        content, is_binary = read_file_safe(f)
        assert is_binary

    def test_png_detected_as_binary(self, tmp_path: Path):
        """PNG files detected as binary (has null bytes in header)."""
        f = tmp_path / "image.png"
        # PNG signature contains null bytes
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        content, is_binary = read_file_safe(f)
        assert is_binary

    def test_latin1_file_with_replacement(self, tmp_path: Path):
        """Non-UTF-8 file returns content with replacement characters."""
        f = tmp_path / "latin.txt"
        # Latin-1 encoded text with non-UTF-8 byte (0xe9 = é in Latin-1)
        f.write_bytes(b"caf\xe9 au lait\n")
        content, is_binary = read_file_safe(f)
        assert not is_binary
        assert "caf" in content
        assert "lait" in content

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        content, is_binary = read_file_safe(f)
        assert not is_binary
        assert content == ""

    def test_mostly_text_with_few_odd_bytes(self, tmp_path: Path):
        """A file with <10% non-text bytes should be treated as text."""
        f = tmp_path / "mostly_text.txt"
        # 95 regular ASCII chars + 5 odd bytes = 5% non-text
        text_bytes = b"a" * 95 + b"\x01" * 5
        f.write_bytes(text_bytes)
        content, is_binary = read_file_safe(f)
        assert not is_binary

    def test_high_non_text_ratio_detected_as_binary(self, tmp_path: Path):
        """A file with >10% non-text bytes (invalid UTF-8) detected as binary."""
        f = tmp_path / "weird.dat"
        # 80 regular chars + 20 invalid-UTF-8 bytes (0xfe is never valid in UTF-8)
        text_bytes = b"x" * 80 + b"\xfe" * 20
        f.write_bytes(text_bytes)
        content, is_binary = read_file_safe(f)
        assert is_binary

    def test_utf8_box_drawing_not_binary(self, tmp_path: Path):
        """UTF-8 files with box-drawing characters must not be flagged binary."""
        f = tmp_path / "decorators.ts"
        # Simulate TS files with Unicode box-drawing separators (U+2500 = ─)
        separator = "// " + "\u2500" * 60 + "\n"
        code = "const x = 1;\n"
        # Enough separators to exceed 10% non-ASCII if checked byte-by-byte
        content = (separator + code) * 30
        f.write_text(content, encoding="utf-8")
        result, is_binary = read_file_safe(f)
        assert not is_binary
        assert "\u2500" in result

    def test_utf8_emoji_not_binary(self, tmp_path: Path):
        """UTF-8 files with emoji / accented characters are text."""
        f = tmp_path / "i18n.py"
        content = "# Héllo wörld 🌍🚀✅\nprint('café')\n" * 20
        f.write_text(content, encoding="utf-8")
        result, is_binary = read_file_safe(f)
        assert not is_binary
        assert "café" in result

