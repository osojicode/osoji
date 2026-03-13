"""Language plugin system for AST-based facts extraction.

Registers first-party plugins on import, then discovers entry-point plugins.
"""

from .base import (
    ExtractedFacts,
    FactsExtractionError,
    LanguagePlugin,
    PluginUnavailableError,
)
from .registry import (
    get_all_plugins,
    plugin_for,
    register_plugin,
    supported_extensions,
    _reset_registry,
    _discover_entry_point_plugins,
)

__all__ = [
    "ExtractedFacts",
    "FactsExtractionError",
    "LanguagePlugin",
    "PluginUnavailableError",
    "get_all_plugins",
    "plugin_for",
    "register_plugin",
    "supported_extensions",
]


def _register_first_party_plugins() -> None:
    """Register built-in plugins."""
    from .python_plugin import PythonPlugin
    from .typescript_plugin import TypeScriptPlugin

    register_plugin(PythonPlugin())
    register_plugin(TypeScriptPlugin())


_register_first_party_plugins()
_discover_entry_point_plugins()
