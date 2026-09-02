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
