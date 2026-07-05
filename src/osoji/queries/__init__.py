"""Generic tree-sitter query loading (V1-6a).

``load_queries("python", language)`` reads every ``.scm`` file under
``osoji/queries/<lang>/`` via ``importlib.resources`` (so it works from a
wheel), compiles each against the given :class:`~tree_sitter.Language`, and
caches the result. Language drivers (e.g. :mod:`osoji.queries.python_driver`)
use the compiled queries as node selectors; the semantic interpretation lives
in the driver.
"""

from __future__ import annotations

from importlib.resources import files

from tree_sitter import Language, Query

_cache: dict[tuple[str, int], dict[str, Query]] = {}


def load_queries(lang_name: str, language: Language) -> dict[str, Query]:
    """Return ``{query-file-stem: compiled Query}`` for a language directory."""

    key = (lang_name, id(language))
    if key not in _cache:
        query_dir = files("osoji.queries").joinpath(lang_name)
        queries: dict[str, Query] = {}
        for entry in query_dir.iterdir():
            if entry.name.endswith(".scm"):
                queries[entry.name[:-4]] = Query(
                    language, entry.read_text(encoding="utf-8")
                )
        if not queries:
            raise FileNotFoundError(
                f"no .scm query files found for language '{lang_name}'"
            )
        _cache[key] = queries
    return _cache[key]
