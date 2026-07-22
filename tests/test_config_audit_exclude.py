"""Tests for `[audit] exclude` glob parsing (osojicode/work#90).

`.osoji.toml` may declare a project-scoped list of repo-relative exclude
globs under `[audit] exclude`. `Config.load_audit_exclude()` reads and
validates that list; absent file / absent table / absent-or-empty key all
mean "no change" (empty list). Malformed shapes raise a clear RuntimeError,
consistent with the rest of the TOML config loading in `config.py`.
"""

from __future__ import annotations

import pytest

from osoji.config import Config, PROJECT_CONFIG_FILENAME


def _write_toml(root, text: str) -> None:
    (root / PROJECT_CONFIG_FILENAME).write_text(text, encoding="utf-8")


def test_no_osoji_toml_returns_empty_list(temp_dir):
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == []


def test_osoji_toml_without_audit_table_returns_empty_list(temp_dir):
    _write_toml(temp_dir, 'default_provider = "openai"\n')
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == []


def test_audit_table_without_exclude_key_returns_empty_list(temp_dir):
    _write_toml(temp_dir, "[audit]\n")
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == []


def test_empty_exclude_list_returns_empty_list(temp_dir):
    _write_toml(temp_dir, "[audit]\nexclude = []\n")
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == []


def test_exclude_list_is_returned_in_order(temp_dir):
    _write_toml(
        temp_dir,
        '[audit]\nexclude = ["docs/archive/**", "vendor/**"]\n',
    )
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == ["docs/archive/**", "vendor/**"]


def test_blank_entries_are_dropped(temp_dir):
    _write_toml(temp_dir, '[audit]\nexclude = ["docs/archive/**", "  ", ""]\n')
    config = Config(root_path=temp_dir)

    assert config.load_audit_exclude() == ["docs/archive/**"]


def test_exclude_not_a_list_raises_runtime_error(temp_dir):
    _write_toml(temp_dir, '[audit]\nexclude = "docs/archive/**"\n')
    config = Config(root_path=temp_dir)

    with pytest.raises(RuntimeError, match="audit.exclude"):
        config.load_audit_exclude()


def test_exclude_entry_not_a_string_raises_runtime_error(temp_dir):
    _write_toml(temp_dir, "[audit]\nexclude = [1, 2]\n")
    config = Config(root_path=temp_dir)

    with pytest.raises(RuntimeError, match="audit.exclude"):
        config.load_audit_exclude()


def test_audit_table_not_a_table_raises_runtime_error(temp_dir):
    _write_toml(temp_dir, 'audit = "not a table"\n')
    config = Config(root_path=temp_dir)

    with pytest.raises(RuntimeError, match=r"\[audit\]"):
        config.load_audit_exclude()


def test_malformed_toml_raises_runtime_error(temp_dir):
    _write_toml(temp_dir, "not valid toml {{{\n")
    config = Config(root_path=temp_dir)

    with pytest.raises(RuntimeError, match="Invalid Osoji config file"):
        config.load_audit_exclude()
