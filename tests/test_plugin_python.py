"""Tests for the Python AST plugin."""

import textwrap

import pytest

from osoji.plugins.python_plugin import PythonPlugin


@pytest.fixture
def plugin():
    return PythonPlugin()


@pytest.fixture
def project(tmp_path):
    """Helper to create project files."""
    class ProjectHelper:
        def __init__(self, root):
            self.root = root
            self.files = []

        def add(self, relative_path, content):
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content), encoding="utf-8")
            self.files.append(path)
            return path

    return ProjectHelper(tmp_path)


def test_basic_extraction(plugin, project):
    project.add("main.py", """\
        import os
        from pathlib import Path

        MY_CONST = 42

        def greet(name):
            print(f"Hello {name}")

        class Greeter:
            def say_hi(self):
                greet("world")
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    assert "main.py" in result

    facts = result["main.py"]
    # Imports
    assert len(facts.imports) == 2
    sources = {imp["source"] for imp in facts.imports}
    assert "os" in sources
    assert "pathlib" in sources

    # Exports
    export_names = {e["name"] for e in facts.exports}
    assert "MY_CONST" in export_names
    assert "greet" in export_names
    assert "Greeter" in export_names
    assert "Greeter.say_hi" in export_names

    # Calls
    call_targets = {c["to"] for c in facts.calls}
    assert "print" in call_targets
    assert "greet" in call_targets


def test_cross_file_call_sites(plugin, project):
    project.add("lib.py", """\
        def helper():
            pass
    """)
    project.add("app.py", """\
        from lib import helper

        def main():
            helper()
            helper()
    """)

    result = plugin.extract_project_facts(project.root, project.files)

    # app.py calls helper() twice
    app_calls = [c for c in result["app.py"].calls if c["to"] == "helper"]
    assert len(app_calls) == 2
    # call_sites should reflect project-wide count
    assert all(c["call_sites"] >= 2 for c in app_calls)


def test_syntax_error_skips_file(plugin, project):
    project.add("good.py", "x = 1\n")
    project.add("bad.py", "def broken(\n")

    result = plugin.extract_project_facts(project.root, project.files)
    assert "good.py" in result
    assert "bad.py" not in result


def test_underscore_excluded_from_exports(plugin, project):
    project.add("mod.py", """\
        _private = 1
        public = 2
        __dunder__ = 3

        def _helper():
            pass

        def public_func():
            pass
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    export_names = {e["name"] for e in result["mod.py"].exports}
    assert "public" in export_names
    assert "public_func" in export_names
    assert "_private" not in export_names
    assert "_helper" not in export_names
    assert "__dunder__" not in export_names


def test_all_overrides_underscore_exclusion(plugin, project):
    project.add("mod.py", """\
        __all__ = ["_special", "public"]

        _special = 1
        _other = 2
        public = 3
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    export_names = {e["name"] for e in result["mod.py"].exports}
    assert "_special" in export_names
    assert "public" in export_names
    assert "_other" not in export_names


def test_decorator_exclusion(plugin, project):
    project.add("mod.py", """\
        from abc import abstractmethod

        class Base:
            @abstractmethod
            def must_implement(self):
                pass

            @property
            def value(self):
                return 42

            def normal_method(self):
                pass
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    exports_by_name = {e["name"]: e for e in result["mod.py"].exports}

    assert exports_by_name["Base.must_implement"]["exclude_from_dead_analysis"] is True
    assert exports_by_name["Base.value"]["exclude_from_dead_analysis"] is True
    assert exports_by_name["Base.normal_method"]["exclude_from_dead_analysis"] is False


def test_relative_import_resolution(plugin, project):
    project.add("pkg/__init__.py", "")
    project.add("pkg/foo.py", """\
        def foo_func():
            pass
    """)
    project.add("pkg/bar.py", """\
        from .foo import foo_func

        def bar_func():
            foo_func()
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    bar_imports = result["pkg/bar.py"].imports
    assert any(imp["source"] == ".foo" for imp in bar_imports)


def test_double_dot_relative_import(plugin, project):
    project.add("pkg/__init__.py", "")
    project.add("pkg/sub/__init__.py", "")
    project.add("pkg/utils.py", """\
        def util_func():
            pass
    """)
    project.add("pkg/sub/deep.py", """\
        from ..utils import util_func
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    deep_imports = result["pkg/sub/deep.py"].imports
    assert any(imp["source"] == "..utils" for imp in deep_imports)


def test_reexport_detection_in_init(plugin, project):
    project.add("pkg/__init__.py", """\
        from .foo import public_func
        from .bar import _private
    """)
    project.add("pkg/foo.py", """\
        def public_func():
            pass
    """)
    project.add("pkg/bar.py", """\
        def _private():
            pass
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    init_imports = result["pkg/__init__.py"].imports
    reexports = [imp for imp in init_imports if imp["is_reexport"]]
    # public_func should be a re-export, _private should not
    reexport_names = []
    for imp in reexports:
        reexport_names.extend(imp["names"])
    assert "public_func" in reexport_names


def test_empty_file(plugin, project):
    project.add("empty.py", "")

    result = plugin.extract_project_facts(project.root, project.files)
    facts = result["empty.py"]
    assert facts.imports == []
    assert facts.exports == []
    assert facts.calls == []
    assert facts.member_writes == []


def test_member_writes(plugin, project):
    project.add("mod.py", """\
        class Config:
            pass

        cfg = Config()
        cfg.name = "test"
        cfg.value = 42
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    writes = result["mod.py"].member_writes
    assert any(w["container"] == "cfg" and w["member"] == "name" for w in writes)
    assert any(w["container"] == "cfg" and w["member"] == "value" for w in writes)


def test_to_file_facts_dict(plugin, project):
    project.add("mod.py", "x = 1\n")

    result = plugin.extract_project_facts(project.root, project.files)
    facts_dict = result["mod.py"].to_file_facts_dict("mod.py", "abc123")

    assert facts_dict["source"] == "mod.py"
    assert facts_dict["source_hash"] == "abc123"
    assert facts_dict["extraction_method"] == "ast"
    assert "imports" in facts_dict
    assert "exports" in facts_dict
    assert "calls" in facts_dict
    assert "member_writes" in facts_dict


def test_filters_to_python_extensions(plugin, project):
    project.add("code.py", "x = 1\n")
    project.add("code.js", "const x = 1;\n")

    result = plugin.extract_project_facts(project.root, project.files)
    assert "code.py" in result
    assert "code.js" not in result


def test_framework_decorator_suffix_match(plugin, project):
    project.add("views.py", """\
        class router:
            @staticmethod
            def get(path):
                def decorator(fn):
                    return fn
                return decorator

        @router.get("/items")
        def list_items():
            return []
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    exports_by_name = {e["name"]: e for e in result["views.py"].exports}
    assert exports_by_name["list_items"]["exclude_from_dead_analysis"] is True


def test_pyi_files_supported(plugin, project):
    project.add("types.pyi", """\
        def typed_func(x: int) -> str: ...
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    assert "types.pyi" in result
    export_names = {e["name"] for e in result["types.pyi"].exports}
    assert "typed_func" in export_names


def test_class_method_exports(plugin, project):
    project.add("mod.py", """\
        class MyClass:
            def method_a(self):
                pass

            async def method_b(self):
                pass
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    export_names = {e["name"] for e in result["mod.py"].exports}
    assert "MyClass" in export_names
    assert "MyClass.method_a" in export_names
    assert "MyClass.method_b" in export_names


def test_annotated_assignment(plugin, project):
    project.add("mod.py", """\
        count: int = 0
        _internal: str = "x"
    """)

    result = plugin.extract_project_facts(project.root, project.files)
    export_names = {e["name"] for e in result["mod.py"].exports}
    assert "count" in export_names
    assert "_internal" not in export_names
