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


def test_script_registry_survives_pyproject_where_project_is_not_a_table(temp_dir):
    """Valid TOML, wrong shape: ``project = "demo"`` must not raise.

    The registry sits on the audit's critical path (phase 2a), so a manifest
    that parses but is not shaped as expected has to degrade to "declares
    nothing", the way the package.json parser already does.
    """
    config = _repo(temp_dir, {
        "pyproject.toml": 'project = "demo"\n',
        "package.json": json.dumps({"scripts": {"build": "tsc"}}),
    })
    reg = ScriptRegistry.from_config(config)

    assert reg.exists("build", "npm").found is True
    assert reg.exists("demo-cli", "python").found is False


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


# --- fix round 4: the index is narrower than the checkout ---------------------


def test_path_registry_marks_ignore_filtered_paths_undecidable_not_absent(temp_dir):
    """A miss inside an ignored prefix is a gap in the index, not an absence.

    ``node_modules`` (and ``.github``, ``build``, ``dist``, ...) are dropped by
    the *source-discovery* filter, which is narrower than the checkout. Calling
    such a miss complete would let the verifier report `contradicted` against a
    file anyone can ``ls`` -- a commission error.
    """
    config = _repo(temp_dir, {"node_modules/x/index.js": "x\n", "src/a.ts": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("node_modules/x/index.js")
    assert answer.found is False
    assert answer.complete is False
    assert "node_modules" in answer.note
    assert answer.near == []


def test_path_registry_marks_osojiignore_filtered_paths_undecidable(temp_dir):
    config = _repo(temp_dir, {
        ".osojiignore": "tests/fixtures\n",
        "tests/fixtures/corpus/README.md": "x\n",
        "src/a.ts": "x\n",
    })
    reg = PathRegistry.from_config(config)

    answer = reg.exists("tests/fixtures/corpus/README.md")
    assert answer.found is False
    assert answer.complete is False
    assert ".osojiignore" in answer.note


def test_path_registry_marks_audit_excluded_globs_undecidable(temp_dir):
    config = _repo(temp_dir, {
        ".osoji.toml": '[audit]\nexclude = ["generated/*"]\n',
        "generated/api.ts": "x\n",
        "src/a.ts": "x\n",
    })
    reg = PathRegistry.from_config(config)

    answer = reg.exists("generated/api.ts")
    assert answer.found is False
    assert answer.complete is False
    assert "[audit] exclude" in answer.note


def test_path_registry_marks_corpus_snapshot_paths_undecidable(temp_dir):
    config = _repo(temp_dir, {
        "cases/case_001/case.json": '{"schema": "corpus-case/1"}',
        "cases/case_001/snapshot/app.py": "x\n",
        "src/a.ts": "x\n",
    })
    reg = PathRegistry.from_config(config)

    answer = reg.exists("cases/case_001/snapshot/app.py")
    assert answer.found is False
    assert answer.complete is False
    assert "corpus-case snapshot" in answer.note


def test_path_registry_treats_a_file_on_disk_but_unindexed_as_undecidable(temp_dir):
    """The catch-all: .gitignore hides files from ``git ls-files`` entirely.

    Those cannot be re-derived from a pattern, so the registry falls back to
    asking the checkout directly. A path that is *there* can never be a
    commission error, whatever the index says.
    """
    (temp_dir / "generated").mkdir()
    (temp_dir / "generated" / "api.ts").write_text("x\n", encoding="utf-8")
    reg = PathRegistry({"README.md"}, root=temp_dir)

    answer = reg.exists("generated/api.ts")
    assert answer.found is False
    assert answer.complete is False
    assert "working tree" in answer.note


def test_path_registry_does_not_stat_outside_the_repository_root(temp_dir):
    reg = PathRegistry({"README.md"}, root=temp_dir)

    answer = reg.exists("../secrets/token.txt")
    assert answer.found is False
    assert answer.complete is False
    assert "escapes the repository root" in answer.note


def test_path_registry_still_contradicts_a_genuinely_absent_path(temp_dir):
    """Signal conservation: the undecidable outlets must not swallow real misses."""
    config = _repo(temp_dir, {"src/server.ts": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("src/servr.ts")
    assert answer.found is False
    assert answer.complete is True
    assert answer.note == ""
    assert "src/server.ts" in answer.near


def test_path_registry_near_match_candidate_set_is_bounded_on_a_large_tree():
    """difflib cost is O(candidates); the candidate set must not be O(tree)."""
    entries = {f"pkg/{i // 100}/mod{i}.ts" for i in range(50_000)}
    reg = PathRegistry(entries)

    candidates = reg.near_candidates("pkg/7/mod7000.ts")

    assert len(candidates) <= 2000
    assert len(candidates) < len(entries) // 10
    # Bounding must not cost the near match itself: same-directory siblings
    # are exactly what a typo'd path is near.
    assert reg.exists("pkg/7/mod7000.ts").near


def test_path_registry_case_error_is_contradicted_on_every_host(temp_dir):
    """Zero-LLM means reproducible from the checkout -- across hosts too.

    ``Path.exists()`` is case-insensitive on Windows and default macOS while
    the entry set is case-sensitive, so the on-disk fallback would answer
    `undecidable` on a dev box and `contradicted` on Linux CI for the same
    claim. A case-error path is also exactly the doc drift that works on one
    filesystem and breaks the build on another.
    """
    config = _repo(temp_dir, {"docs/guide.md": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("docs/Guide.md")
    assert answer.found is False
    assert answer.complete is True
    assert answer.note == ""


def test_path_registry_case_exact_unindexed_file_is_still_undecidable(temp_dir):
    """The case check must not undo the fix it is guarding."""
    (temp_dir / "generated").mkdir()
    (temp_dir / "generated" / "api.ts").write_text("x\n", encoding="utf-8")
    # `generated` is indexed (the anchor rule needs the root segment in the
    # tree) while `generated/api.ts` itself is not -- the case this guards.
    reg = PathRegistry({"README.md", "generated", "generated/other.ts"}, root=temp_dir)

    assert reg.exists("generated/api.ts").complete is False
    assert reg.exists("generated/API.ts").complete is True


# --- rulings wave: the anchor rule -------------------------------------------


def test_path_claim_whose_root_segment_is_absent_from_the_tree_is_undecidable(temp_dir):
    """A repo-relative claim is only decidable when its root is in the repo.

    `tools/list` is an MCP RPC method name, `osojicode/osoji` an org slug,
    `openai/gpt-5-mini` a model id -- none of them addresses this checkout, and
    the registry cannot contradict a claim that was never about the tree. The
    test is the first segment, because that is what a repo-relative path and a
    foreign namespace disagree about.
    """
    config = _repo(temp_dir, {"src/server.ts": "x\n", "README.md": "# x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("tools/list")

    assert answer.found is False
    assert answer.complete is False
    assert answer.note == "root segment not in the tree; not a repo-relative claim"
    assert answer.near == []


def test_path_claim_under_a_real_top_level_directory_still_contradicts(temp_dir):
    """Signal conservation: the anchor rule must not swallow real misses."""
    config = _repo(temp_dir, {"src/server.ts": "x\n"})
    reg = PathRegistry.from_config(config)

    answer = reg.exists("src/nope.ts")

    assert answer.found is False
    assert answer.complete is True
    assert answer.note == ""


def test_anchor_rule_accepts_a_top_level_file_as_the_root_segment(temp_dir):
    """A root segment may be a file as well as a directory (`README.md#x`)."""
    config = _repo(temp_dir, {"README.md": "# x\n"})
    reg = PathRegistry.from_config(config)

    assert reg.exists("README.md/nope").complete is True
