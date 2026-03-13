"""Tests for plugin registry."""

from unittest.mock import patch, MagicMock

import pytest

from osoji.plugins.base import LanguagePlugin
from osoji.plugins.registry import (
    register_plugin,
    plugin_for,
    get_all_plugins,
    supported_extensions,
    _reset_registry,
    _discover_entry_point_plugins,
)


class FakePlugin(LanguagePlugin):
    @property
    def name(self) -> str:
        return "fake"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".fake", ".fk"})

    def extract_project_facts(self, project_root, files):
        return {}


class AnotherPlugin(LanguagePlugin):
    @property
    def name(self) -> str:
        return "another"

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset({".fake"})  # overlaps with FakePlugin

    def extract_project_facts(self, project_root, files):
        return {}


@pytest.fixture(autouse=True)
def clean_registry():
    _reset_registry()
    yield
    _reset_registry()


def test_register_and_lookup():
    plugin = FakePlugin()
    register_plugin(plugin)

    assert plugin_for("test.fake") is plugin
    assert plugin_for("test.fk") is plugin


def test_unknown_extension_returns_none():
    assert plugin_for("test.unknown") is None


def test_re_register_overwrites():
    plugin1 = FakePlugin()
    plugin2 = AnotherPlugin()

    register_plugin(plugin1)
    assert plugin_for("test.fake") is plugin1

    register_plugin(plugin2)
    assert plugin_for("test.fake") is plugin2


def test_get_all_plugins_deduplicates():
    plugin = FakePlugin()
    register_plugin(plugin)

    # Same plugin registered for .fake and .fk
    all_plugins = get_all_plugins()
    assert len(all_plugins) == 1
    assert all_plugins[0] is plugin


def test_get_all_plugins_multiple():
    p1 = FakePlugin()
    p2 = AnotherPlugin()
    register_plugin(p1)
    register_plugin(p2)

    all_plugins = get_all_plugins()
    # p2 overwrites .fake from p1, but p1 still has .fk
    assert len(all_plugins) == 2


def test_supported_extensions():
    register_plugin(FakePlugin())
    exts = supported_extensions()
    assert ".fake" in exts
    assert ".fk" in exts


def test_reset_registry():
    register_plugin(FakePlugin())
    assert plugin_for("test.fake") is not None

    _reset_registry()
    assert plugin_for("test.fake") is None


def test_entry_point_discovery_handles_broken_plugin():
    """Entry point discovery should log warning on failure, not crash."""
    mock_ep = MagicMock()
    mock_ep.name = "broken"
    mock_ep.load.side_effect = ImportError("boom")

    with patch("osoji.plugins.registry.importlib.metadata.entry_points", return_value=[mock_ep]):
        # Should not raise
        _discover_entry_point_plugins()

    # Registry should still be empty (broken plugin not registered)
    assert plugin_for("test.fake") is None


def test_entry_point_discovery_registers_valid_plugin():
    mock_ep = MagicMock()
    mock_ep.name = "test_plugin"
    mock_ep.load.return_value = FakePlugin

    with patch("osoji.plugins.registry.importlib.metadata.entry_points", return_value=[mock_ep]):
        _discover_entry_point_plugins()

    assert plugin_for("test.fake") is not None


def test_entry_point_discovery_handles_no_entry_points():
    with patch("osoji.plugins.registry.importlib.metadata.entry_points", side_effect=Exception("no group")):
        # Should not raise
        _discover_entry_point_plugins()
