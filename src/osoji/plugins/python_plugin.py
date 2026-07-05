"""Python language plugin — tree-sitter backed as of V1-6a.

Compatibility shim: the implementation lives in
:mod:`osoji.queries.python_driver`; existing imports of
``osoji.plugins.python_plugin.PythonPlugin`` keep working. The pre-migration
``ast``-based implementation is preserved as
:mod:`osoji.plugins._legacy_python_ast` for the parity soak and is deleted in
a follow-up once the tree-sitter plugin has baked.
"""

from ..queries.python_driver import PythonPlugin

__all__ = ["PythonPlugin"]
