"""Tests for dead CI/CD detection."""

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from osoji.config import Config
from osoji.junk import JunkAnalysisResult
from osoji.junk_cicd import (
    CICDCandidate,
    CICDElement,
    DeadCICDAnalyzer,
    _check_path_references,
    _extract_paths_from_command,
    _parse_cicd_via_llm,
    _parse_github_workflow,
    _parse_gitlab_ci,
    _parse_makefile,
    detect_dead_cicd_async,
    discover_cicd_files,
)
from osoji.llm.types import CompletionResult, ToolCall


def _triage_verdicts(options, verdicts_by_index):
    """Build a submit_triage_verdicts ToolCall response for a triage batch."""
    validator = options.tool_input_validators[0]
    n = len(validator("submit_triage_verdicts", {"verdicts": []}))
    verdicts = []
    for i in range(n):
        verdict, confidence, reasoning = verdicts_by_index.get(
            i, ("confirmed", 0.85, "referenced path removed")
        )
        verdicts.append({
            "batch_index": i, "verdict": verdict, "confidence": confidence,
            "reasoning": reasoning,
        })
    return CompletionResult(
        content=None,
        tool_calls=[ToolCall(
            id="triage", name="submit_triage_verdicts",
            input={"verdicts": verdicts},
        )],
        input_tokens=200, output_tokens=80, model="test", stop_reason="tool_use",
    )


# --- Helpers ---

def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


# --- TestDiscoverCICDFiles ---

class TestDiscoverCICDFiles:
    def test_finds_github_workflows(self, temp_dir):
        _write_source(temp_dir, ".github/workflows/ci.yml", "name: CI\n")
        _write_source(temp_dir, ".github/workflows/deploy.yaml", "name: Deploy\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        names = [p.name for p, _ in found]
        assert "ci.yml" in names
        assert "deploy.yaml" in names
        types = {p.name: t for p, t in found}
        assert types["ci.yml"] == "github_workflow"

    def test_finds_makefile(self, temp_dir):
        _write_source(temp_dir, "Makefile", "all:\n\techo hello\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        names = [p.name for p, _ in found]
        assert "Makefile" in names
        types = {p.name: t for p, t in found}
        assert types["Makefile"] == "makefile"

    def test_finds_gitlab_ci(self, temp_dir):
        _write_source(temp_dir, ".gitlab-ci.yml", "stages:\n  - test\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        names = [p.name for p, _ in found]
        assert ".gitlab-ci.yml" in names

    def test_skips_missing(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        assert found == []

    def test_finds_multiple_types(self, temp_dir):
        _write_source(temp_dir, ".github/workflows/ci.yml", "name: CI\n")
        _write_source(temp_dir, "Makefile", "all:\n\techo hello\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        types = {t for _, t in found}
        assert "github_workflow" in types
        assert "makefile" in types
        assert len(found) >= 2


# --- TestParseGithubWorkflow ---

class TestParseGithubWorkflow:
    def test_extracts_jobs(self):
        content = textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              test:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                  - run: pytest tests/
              lint:
                runs-on: ubuntu-latest
                steps:
                  - run: ruff check src/
        """)
        elements = _parse_github_workflow(content, ".github/workflows/ci.yml")
        names = [e.element_name for e in elements]
        assert "test" in names
        assert "lint" in names

    def test_extracts_run_commands(self):
        content = textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              build:
                runs-on: ubuntu-latest
                steps:
                  - run: python setup.py build
                  - run: python -m pytest tests/unit/
        """)
        elements = _parse_github_workflow(content, ".github/workflows/ci.yml")
        assert len(elements) == 1
        elem = elements[0]
        assert elem.element_name == "build"
        assert any("pytest" in cmd for cmd in elem.referenced_commands)

    def test_extracts_uses_references(self):
        content = textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              deploy:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                  - uses: docker/build-push-action@v5
        """)
        elements = _parse_github_workflow(content, ".github/workflows/ci.yml")
        assert len(elements) == 1
        assert any("actions/checkout" in cmd for cmd in elements[0].referenced_commands)

    def test_multiline_run_block(self):
        content = textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              test:
                runs-on: ubuntu-latest
                steps:
                  - run: |
                      pip install -e .
                      pytest tests/
        """)
        elements = _parse_github_workflow(content, ".github/workflows/ci.yml")
        assert len(elements) == 1
        # Should have extracted commands from multiline block
        assert len(elements[0].referenced_commands) >= 1

    def test_no_jobs_section(self):
        content = "name: CI\non: push\n"
        elements = _parse_github_workflow(content, ".github/workflows/ci.yml")
        assert elements == []


# --- TestParseMakefile ---

class TestParseMakefile:
    def test_extracts_targets(self):
        content = """all: build test

build:
\tpython setup.py build

test:
\tpytest tests/

clean:
\trm -rf build/ dist/
"""
        elements = _parse_makefile(content, "Makefile")
        names = [e.element_name for e in elements]
        assert "all" in names
        assert "build" in names
        assert "test" in names
        assert "clean" in names

    def test_extracts_recipe_commands(self):
        content = """build:
\tpython setup.py build
\tcp dist/app.bin /usr/local/bin/
"""
        elements = _parse_makefile(content, "Makefile")
        assert len(elements) == 1
        assert len(elements[0].referenced_commands) == 2

    def test_phony_targets(self):
        content = """.PHONY: test
test:
\tpytest tests/
"""
        elements = _parse_makefile(content, "Makefile")
        # .PHONY is a valid target name pattern (starts with .)
        names = [e.element_name for e in elements]
        assert "test" in names

    def test_empty_makefile(self):
        content = "# Just a comment\n"
        elements = _parse_makefile(content, "Makefile")
        assert elements == []


# --- TestExtractPaths ---

class TestExtractPaths:
    def test_filters_flags(self):
        paths = _extract_paths_from_command("ls -la --color=auto")
        assert not any(p.startswith("-") for p in paths)

    def test_filters_urls(self):
        paths = _extract_paths_from_command("curl https://example.com/file.tar.gz")
        assert not any(p.startswith("http") for p in paths)

    def test_keeps_file_paths(self):
        paths = _extract_paths_from_command("cp src/app.py dist/app.py")
        assert "src/app.py" in paths
        assert "dist/app.py" in paths

    def test_handles_quoted_paths(self):
        paths = _extract_paths_from_command('cp "src/my file.py" dest/')
        path_strs = [p for p in paths]
        assert any("src" in p for p in path_strs)

    def test_filters_common_commands(self):
        paths = _extract_paths_from_command("echo hello")
        assert "echo" not in paths
        assert "hello" not in paths  # no / or . in hello


# --- TestCheckPathReferences ---

class TestCheckPathReferences:
    def test_correct_missing_vs_present(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")
        # Don't create tests/old_test.py

        elements = [CICDElement(
            cicd_file=".github/workflows/ci.yml",
            element_type="workflow_job",
            element_name="test",
            line_start=1,
            line_end=5,
            referenced_paths=["src/app.py", "tests/old_test.py"],
            referenced_commands=["pytest tests/old_test.py"],
        )]
        _check_path_references(config, elements)
        # src/app.py exists, tests/old_test.py does not
        assert "tests/old_test.py" in elements[0].missing_paths
        assert "src/app.py" not in elements[0].missing_paths

    def test_all_paths_present(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")

        elements = [CICDElement(
            cicd_file=".github/workflows/ci.yml",
            element_type="workflow_job",
            element_name="test",
            line_start=1,
            line_end=5,
            referenced_paths=["src/app.py"],
            referenced_commands=["python src/app.py"],
        )]
        _check_path_references(config, elements)
        assert elements[0].missing_paths == []


# NOTE: CI/CD verification moved from the deleted `_verify_batch_async` to the
# unified Triage pipeline (V1-5b). The still-active taxonomy (external deploy
# tools, dynamic test discovery, phony targets) is now judged by Triage under
# the reachability rubric's dead-CI/CD clause; see
# tests/test_junk_project_graph_cutover.py for the confirmed/dismissed gate.


# --- TestDetectDeadCICDAsync ---

class TestDetectDeadCICDAsync:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # Create a workflow that references a missing path. cicd_files is passed
        # explicitly so the run is deterministic across filesystem case rules.
        _write_source(temp_dir, ".github/workflows/ci.yml", textwrap.dedent("""\
            name: CI
            on: push
            jobs:
              test:
                runs-on: ubuntu-latest
                steps:
                  - run: pytest tests/removed_dir/
        """))
        _write_source(temp_dir, "src/app.py", "print('hello')\n")
        # Don't create tests/removed_dir/

        mock_provider = AsyncMock()

        async def mock_complete(**kwargs):
            options = kwargs.get("options")
            return _triage_verdicts(options, {
                0: ("confirmed", 0.85, "references removed test directory"),
            })

        mock_provider.complete.side_effect = mock_complete

        decided, total = await detect_dead_cicd_async(
            mock_provider, config,
            cicd_files=[(temp_dir / ".github" / "workflows" / "ci.yml", "github_workflow")],
        )
        assert total == 1
        confirmed = [f for f in decided if f.verdict == "confirmed"]
        assert [f.symbol for f in confirmed] == ["test"]

    @pytest.mark.asyncio
    async def test_no_cicd_files(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")

        mock_provider = AsyncMock()
        decided, total = await detect_dead_cicd_async(mock_provider, config)
        assert (decided, total) == ([], 0)
        mock_provider.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_paths_present_no_candidates(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")
        _write_source(temp_dir, "Makefile", "test:\n\tpython src/app.py\n")

        mock_provider = AsyncMock()
        decided, total = await detect_dead_cicd_async(
            mock_provider, config,
            cicd_files=[(temp_dir / "Makefile", "makefile")],
        )
        # src/app.py exists, so no missing paths, so no LLM call
        assert (decided, total) == ([], 0)
        mock_provider.complete.assert_not_called()


# --- TestDeadCICDAnalyzer ---

class TestDeadCICDAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_async_returns_junk_result(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "Makefile", "deploy:\n\tbash scripts/deploy.sh\n")
        # Don't create scripts/deploy.sh

        mock_provider = AsyncMock()

        async def mock_complete(**kwargs):
            options = kwargs.get("options")
            return _triage_verdicts(options, {
                0: ("confirmed", 0.9, "deploy script no longer exists"),
            })

        mock_provider.complete.side_effect = mock_complete

        analyzer = DeadCICDAnalyzer()
        # cicd_files passed explicitly so discovery's case-insensitive Makefile
        # probing does not double-count on the host filesystem.
        result = await analyzer.analyze_async(
            mock_provider, config,
            cicd_files=[(temp_dir / "Makefile", "makefile")],
        )

        assert isinstance(result, JunkAnalysisResult)
        assert result.analyzer_name == "dead_cicd"
        assert result.total_candidates == 1

        finding = result.findings[0]
        assert finding.source_path == "Makefile"
        assert finding.name == "deploy"
        assert finding.kind == "makefile_target"
        assert finding.category == "dead_cicd"

    def test_analyzer_properties(self):
        analyzer = DeadCICDAnalyzer()
        assert analyzer.name == "dead_cicd"
        assert analyzer.cli_flag == "dead-cicd"
        assert "ci/cd" in analyzer.description.lower() or "cicd" in analyzer.description.lower()

    def test_is_junk_analyzer_subclass(self):
        from osoji.junk import JunkAnalyzer
        assert issubclass(DeadCICDAnalyzer, JunkAnalyzer)


# --- TestParseGitlabCI ---

class TestParseGitlabCI:
    def test_extracts_jobs(self):
        content = textwrap.dedent("""\
            stages:
              - build
              - test

            build_job:
              stage: build
              script:
                - make build

            test_job:
              stage: test
              script:
                - pytest tests/
        """)
        elements = _parse_gitlab_ci(content, ".gitlab-ci.yml")
        names = [e.element_name for e in elements]
        assert "build_job" in names
        assert "test_job" in names

    def test_skips_reserved_keys(self):
        content = textwrap.dedent("""\
            stages:
              - test
            variables:
              CI: "true"
            default:
              image: python:3.11
            include:
              - local: .ci/common.yml
            workflow:
              rules:
                - if: $CI_PIPELINE_SOURCE == "push"
            artifacts:
              paths:
                - build/
            real_job:
              script:
                - echo hello
        """)
        elements = _parse_gitlab_ci(content, ".gitlab-ci.yml")
        names = [e.element_name for e in elements]
        # Only real_job should be extracted, all others are reserved
        assert "real_job" in names
        assert "stages" not in names
        assert "variables" not in names
        assert "default" not in names
        assert "include" not in names
        assert "workflow" not in names
        assert "artifacts" not in names

    def test_expanded_reserved_keys(self):
        """Verify the expanded reserved_keys set correctly filters new keys."""
        content = textwrap.dedent("""\
            pages:
              script:
                - deploy
            retry:
              max: 2
            timeout:
              value: 30m
            my_actual_job:
              script:
                - echo hello
        """)
        elements = _parse_gitlab_ci(content, ".gitlab-ci.yml")
        names = [e.element_name for e in elements]
        assert "my_actual_job" in names
        assert "pages" not in names
        assert "retry" not in names
        assert "timeout" not in names


# --- TestHaikuCICDParsing ---

class TestHaikuCICDParsing:
    @pytest.mark.asyncio
    async def test_parses_jenkinsfile(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="extract_cicd_elements",
                input={
                    "elements": [
                        {
                            "element_name": "Build",
                            "element_type": "stage",
                            "line_start": 3,
                            "line_end": 8,
                            "referenced_paths": ["src/"],
                            "referenced_commands": ["sh 'mvn clean package'"],
                        },
                        {
                            "element_name": "Test",
                            "element_type": "stage",
                            "line_start": 9,
                            "line_end": 14,
                            "referenced_paths": ["tests/"],
                            "referenced_commands": ["sh 'mvn test'"],
                        },
                    ],
                },
            )],
            input_tokens=200, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        content = textwrap.dedent("""\
            pipeline {
              agent any
              stages {
                stage('Build') {
                  steps {
                    sh 'mvn clean package'
                  }
                }
                stage('Test') {
                  steps {
                    sh 'mvn test'
                  }
                }
              }
            }
        """)
        elements, in_tok, out_tok = await _parse_cicd_via_llm(
            mock_provider, content, "Jenkinsfile", "jenkinsfile",
        )
        assert len(elements) == 2
        assert elements[0].element_name == "Build"
        assert elements[0].element_type == "stage"
        assert elements[0].cicd_file == "Jenkinsfile"
        assert in_tok == 200

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty(self):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="extract_cicd_elements",
                input={"elements": []},
            )],
            input_tokens=100, output_tokens=30,
            model="test", stop_reason="tool_use",
        )

        elements, _, _ = await _parse_cicd_via_llm(
            mock_provider, "# empty", "Jenkinsfile", "jenkinsfile",
        )
        assert elements == []


# --- TestDiscoverUnsupportedTypes ---

class TestDiscoverUnsupportedTypes:
    def test_discovers_jenkinsfile(self, temp_dir):
        _write_source(temp_dir, "Jenkinsfile", "pipeline { agent any }\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        types = {t for _, t in found}
        assert "jenkinsfile" in types

    def test_discovers_circleci(self, temp_dir):
        _write_source(temp_dir, ".circleci/config.yml", "version: 2.1\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        types = {t for _, t in found}
        assert "circleci" in types

    def test_discovers_azure_pipelines(self, temp_dir):
        _write_source(temp_dir, "azure-pipelines.yml", "trigger: main\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        types = {t for _, t in found}
        assert "azure_pipelines" in types

    def test_discovers_travis_ci(self, temp_dir):
        _write_source(temp_dir, ".travis.yml", "language: python\n")
        config = Config(root_path=temp_dir, respect_gitignore=False)
        found = discover_cicd_files(config)
        types = {t for _, t in found}
        assert "travis_ci" in types
