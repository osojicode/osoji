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


# --- String literal extraction tests ---


def _strings_by_usage(facts, usage):
    """Helper: return set of string values with a given usage."""
    return {s["value"] for s in facts.string_literals if s.get("usage") == usage}


def test_dict_value_extracted_as_produced(plugin, project):
    project.add("config.py", """\
        _MANIFEST_FILES = {
            "pyproject.toml": "python",
            "package.json": "node",
            "Cargo.toml": "rust",
            "go.mod": "go",
        }
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    produced = _strings_by_usage(result["config.py"], "produced")
    assert {"python", "node", "rust", "go"} <= produced


def test_equality_comparison_extracted_as_checked(plugin, project):
    project.add("handler.py", """\
        def handle(ecosystem):
            if ecosystem == "python":
                return True
            if ecosystem == "node":
                return True
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    facts = result["handler.py"]
    checked = [s for s in facts.string_literals if s.get("usage") == "checked"]
    checked_values = {s["value"] for s in checked}
    assert "python" in checked_values
    assert "node" in checked_values
    # comparison_source should be resolved
    for s in checked:
        if s["value"] in ("python", "node"):
            assert s.get("comparison_source") == "ecosystem"


def test_constant_assignment_extracted_as_defined(plugin, project):
    project.add("constants.py", """\
        MODE = "production"
        DEBUG_LEVEL = "verbose"
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    defined = _strings_by_usage(result["constants.py"], "defined")
    assert "production" in defined
    assert "verbose" in defined


def test_return_value_extracted_as_produced(plugin, project):
    project.add("util.py", """\
        def status():
            return "success"
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    produced = _strings_by_usage(result["util.py"], "produced")
    assert "success" in produced


def test_default_param_extracted_as_produced(plugin, project):
    project.add("api.py", """\
        def connect(mode="auto", host="localhost"):
            pass
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    produced = _strings_by_usage(result["api.py"], "produced")
    assert "auto" in produced
    assert "localhost" in produced


def test_collection_element_extracted_as_produced(plugin, project):
    project.add("choices.py", """\
        MODES = ["fast", "slow", "balanced"]
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    produced = _strings_by_usage(result["choices.py"], "produced")
    assert {"fast", "slow", "balanced"} <= produced


def test_docstring_skipped(plugin, project):
    project.add("mod.py", """\
        \"\"\"This is a module docstring.\"\"\"

        def func():
            \"\"\"This is a function docstring.\"\"\"
            return "real_value"
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    all_values = {s["value"] for s in result["mod.py"].string_literals}
    assert "This is a module docstring." not in all_values
    assert "This is a function docstring." not in all_values
    assert "real_value" in all_values


def test_single_char_skipped(plugin, project):
    project.add("mod.py", """\
        x = "a"
        y = "ab"
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    all_values = {s["value"] for s in result["mod.py"].string_literals}
    assert "a" not in all_values
    assert "ab" in all_values


def test_in_operator_extracted_as_checked(plugin, project):
    project.add("checker.py", """\
        def check(data):
            if "key_name" in data:
                return True
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    checked = [s for s in result["checker.py"].string_literals if s.get("usage") == "checked"]
    assert any(s["value"] == "key_name" for s in checked)
    for s in checked:
        if s["value"] == "key_name":
            assert s.get("comparison_source") == "data"


def test_dict_values_and_checks_both_extracted(plugin, project):
    """The key test: same string as dict value AND equality check → both usages captured."""
    project.add("junk_deps.py", """\
        _MANIFEST_FILES = {
            "pyproject.toml": "python",
            "package.json": "node",
        }

        def resolve(ecosystem):
            if ecosystem == "python":
                return ["pip"]
            if ecosystem == "node":
                return ["npm"]
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    facts = result["junk_deps.py"]
    produced = _strings_by_usage(facts, "produced")
    checked = _strings_by_usage(facts, "checked")
    # Both usages present for each string
    assert "python" in produced
    assert "python" in checked
    assert "node" in produced
    assert "node" in checked


def test_to_file_facts_dict_includes_string_literals(plugin, project):
    project.add("mod.py", """\
        STATUS = "active"
    """)
    result = plugin.extract_project_facts(project.root, project.files)
    d = result["mod.py"].to_file_facts_dict("mod.py", "hash123")
    assert "string_literals" in d
    assert any(s["value"] == "active" for s in d["string_literals"])


def test_to_file_facts_dict_omits_none_string_literals():
    from osoji.plugins.base import ExtractedFacts
    ef = ExtractedFacts()
    d = ef.to_file_facts_dict("x.ts", "hash")
    assert "string_literals" not in d
