"""Tests for shadow doc write retry and directory error handling."""

import asyncio
import errno
from pathlib import Path
from unittest.mock import patch

import pytest

from osoji.shadow import _write_with_retry


@pytest.fixture
def tmp_file(tmp_path):
    return tmp_path / "test.txt"


class TestWriteWithRetry:
    """Tests for _write_with_retry."""

    def test_succeeds_on_first_attempt(self, tmp_file):
        asyncio.run(_write_with_retry(tmp_file, "hello"))
        assert tmp_file.read_text(encoding="utf-8") == "hello"

    def test_retries_on_einval_then_succeeds(self, tmp_file):
        call_count = 0
        original_write = Path.write_text

        def flaky_write(self_path, content, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError(errno.EINVAL, "Invalid argument")
            return original_write(self_path, content, *args, **kwargs)

        with patch.object(Path, "write_text", flaky_write):
            asyncio.run(_write_with_retry(tmp_file, "hello"))

        assert call_count == 2
        assert tmp_file.read_text(encoding="utf-8") == "hello"

    def test_retries_on_eio_then_succeeds(self, tmp_file):
        call_count = 0
        original_write = Path.write_text

        def flaky_write(self_path, content, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError(errno.EIO, "Input/output error")
            return original_write(self_path, content, *args, **kwargs)

        with patch.object(Path, "write_text", flaky_write):
            asyncio.run(_write_with_retry(tmp_file, "hello"))

        assert call_count == 3

    def test_raises_after_all_retries_exhausted(self, tmp_file):
        def always_fail(self_path, content, *args, **kwargs):
            raise OSError(errno.EINVAL, "Invalid argument")

        with patch.object(Path, "write_text", always_fail):
            with pytest.raises(OSError, match="Invalid argument"):
                asyncio.run(_write_with_retry(tmp_file, "hello"))

    def test_non_transient_error_raises_immediately(self, tmp_file):
        call_count = 0

        def perm_error(self_path, content, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise OSError(errno.EACCES, "Permission denied")

        with patch.object(Path, "write_text", perm_error):
            with pytest.raises(OSError, match="Permission denied"):
                asyncio.run(_write_with_retry(tmp_file, "hello"))

        assert call_count == 1  # No retries for non-transient errors
