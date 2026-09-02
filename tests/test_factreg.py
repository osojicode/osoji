"""Tests for the mechanical fact registries (Tier A)."""

from pathlib import Path

from osoji.config import Config
from osoji.factreg import PathRegistry


def _repo(temp_dir: Path, files: dict[str, str]) -> Config:
    for rel, content in files.items():
        p = temp_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return Config(root_path=temp_dir, respect_gitignore=False)


def test_path_registry_finds_tracked_file_and_its_directories(temp_dir):
    config = _repo(temp_dir, {"src/app/main.ts": "export {}\n", "README.md": "# x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("src/app/main.ts").found is True
    assert reg.exists("src/app").found is True
    assert reg.exists("src").found is True
    assert reg.exists("README.md").found is True


def test_path_registry_normalizes_separators_and_leading_dot_slash(temp_dir):
    config = _repo(temp_dir, {"docs/guide.md": "x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("./docs/guide.md").found is True
    assert reg.exists("docs\\guide.md").found is True
    assert reg.exists("docs/guide.md/").found is True


def test_path_registry_reports_absence_with_near_matches(temp_dir):
    config = _repo(temp_dir, {"scripts/check-docs.mjs": "x\n", "scripts/check-deps.mjs": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("scripts/check-doc.mjs")
    assert answer.found is False
    assert answer.namespace == "paths"
    assert answer.complete is True
    assert "scripts/check-docs.mjs" in answer.near
    assert answer.locations == []


def test_path_registry_marks_ignored_paths_absent(temp_dir):
    config = _repo(temp_dir, {"node_modules/x/index.js": "x\n", "src/a.ts": "x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("node_modules/x/index.js").found is False
    assert reg.size >= 2


import json
import textwrap

from osoji.factreg import ScriptRegistry


def test_script_registry_reads_package_json_scripts_across_workspaces(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"name": "root", "scripts": {"build": "tsc -b", "test:unit": "vitest run"}}),
        "packages/api/package.json": json.dumps({"name": "api", "scripts": {"dev:server": "node dist/server.js"}}),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("test:unit", "npm").found is True
    assert reg.exists("dev:server", "npm").found is True
    assert reg.exists("test:unit", "npm").locations[0].path == "package.json"
    assert sorted(reg.manifests) == ["package.json", "packages/api/package.json"]


def test_script_registry_absent_script_reports_near_matches_and_namespace(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"scripts": {"test": "vitest", "test:unit": "vitest run", "test:e2e": "playwright"}}),
    })
    reg = ScriptRegistry.from_config(config)

    answer = reg.exists("test:ui", "npm")
    assert answer.found is False
    assert answer.complete is True
    assert answer.namespace == "scripts"
    assert answer.searched == ["package.json#scripts"]
    assert "test:unit" in answer.near


def test_script_registry_reads_makefile_targets_and_pyproject_scripts(temp_dir):
    config = _repo(temp_dir, {
        "Makefile": textwrap.dedent("""\
            .PHONY: lint
            lint:
            \truff check .
            build: lint
            \tpython -m build
            """),
        "pyproject.toml": textwrap.dedent("""\
            [project]
            name = "demo"
            [project.scripts]
            demo-cli = "demo.cli:main"
            """),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("lint", "make").found is True
    assert reg.exists("build", "make").found is True
    assert reg.exists("demo-cli", "python").found is True
    assert reg.exists("deploy", "make").found is False


def test_script_registry_is_undecidable_when_no_manifest_of_that_ecosystem_exists(temp_dir):
    config = _repo(temp_dir, {"README.md": "# no manifests\n"})
    reg = ScriptRegistry.from_config(config)

    answer = reg.exists("build", "npm")
    assert answer.found is False
    assert answer.complete is False
    assert answer.searched == []


def test_script_registry_any_ecosystem_lookup(temp_dir):
    config = _repo(temp_dir, {
        "package.json": json.dumps({"scripts": {"build": "tsc"}}),
        "Makefile": "test:\n\tpytest\n",
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("build").found is True
    assert reg.exists("test").found is True
    assert reg.exists("nope").found is False


def test_script_registry_ignores_manifests_under_default_ignored_dirs(temp_dir):
    config = _repo(temp_dir, {
        "node_modules/some-dep/package.json": json.dumps(
            {"name": "some-dep", "scripts": {"postinstall": "node build.js"}}
        ),
        "package.json": json.dumps({"name": "root", "scripts": {"build": "tsc"}}),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("postinstall", "npm").found is False
    assert reg.exists("build", "npm").found is True
    assert reg.manifests == ["package.json"]
