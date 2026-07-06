"""Tests for UTF-8 console output configuration.

Findings contain arbitrary LLM-generated Unicode; report printing must not
assume the console locale can represent it. On Windows cp1252 consoles,
printing a finding containing characters like '→' crashed with
UnicodeEncodeError after the audit itself had already succeeded.
"""

import io
import sys

from click.testing import CliRunner

import osoji.cli
from osoji.cli import _configure_utf8_output, main


def _cp1252_stream() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")


def test_cp1252_stdout_prints_non_ascii_without_error(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _cp1252_stream())
    monkeypatch.setattr(sys, "stderr", _cp1252_stream())

    _configure_utf8_output()

    # '→' has no cp1252 encoding; without reconfiguration this raises
    # UnicodeEncodeError.
    print("dead_symbol → removed", file=sys.stdout)
    print("warning → detail", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    assert "→".encode("utf-8") in sys.stdout.buffer.getvalue()
    assert "→".encode("utf-8") in sys.stderr.buffer.getvalue()


def test_stream_without_reconfigure_is_tolerated(monkeypatch):
    # io.StringIO has no reconfigure(); the helper must degrade gracefully
    # rather than crash on exotic stream replacements.
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    _configure_utf8_output()

    print("plain", file=sys.stdout)


def test_main_callback_configures_output(monkeypatch):
    calls = []
    monkeypatch.setattr(osoji.cli, "_configure_utf8_output", lambda: calls.append(True))
    runner = CliRunner()

    result = runner.invoke(main, ["skills", "list"])

    assert result.exit_code == 0
    assert calls, "main() group callback must configure output encoding"
