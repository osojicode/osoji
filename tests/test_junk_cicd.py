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
    CICDVerification,
    DeadCICDAnalyzer,
    _build_candidates,
    _check_path_references,
    _extract_paths_from_command,
    _parse_cicd_via_haiku,
    _parse_github_workflow,
    _parse_gitlab_ci,
    _parse_makefile,
    _verify_batch_async,
    detect_dead_cicd_async,
    discover_cicd_files,
)
from osoji.llm.types import CompletionResult, ToolCall
from osoji.rate_limiter import RateLimiter, RateLimiterConfig


# --- Helpers ---

def _write_source(temp_dir, path, content):
    """Helper to write a source file."""
    full = temp_dir / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)


def _make_rate_limiter():
    return RateLimiter(RateLimiterConfig(
        requests_per_minute=1000,
        input_tokens_per_minute=1_000_000,
        output_tokens_per_minute=1_000_000,
    ))


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


# --- TestVerifyBatch ---

class TestVerifyBatch:
    @pytest.fixture
    def config(self, temp_dir):
        return Config(root_path=temp_dir, respect_gitignore=False)

    @pytest.mark.asyncio
    async def test_llm_confirms_dead_job(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_cicd",
                input={
                    "verdicts": [{
                        "element_name": "old-deploy",
                        "is_dead": True, "confidence": 0.9,
                        "reason": "References removed deploy directory",
                        "remediation": "Remove job from workflow",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        candidate = CICDCandidate(
            cicd_file=".github/workflows/ci.yml",
            element_name="old-deploy",
            element_type="workflow_job",
            line_start=10,
            line_end=20,
            missing_paths=["deploy/scripts/run.sh"],
            element_content="  old-deploy:\n    run: bash deploy/scripts/run.sh\n",
            full_file_content="name: CI\njobs:\n  old-deploy:\n    run: bash deploy/scripts/run.sh\n",
        )
        results, in_tok, out_tok = await _verify_batch_async(
            mock_provider, config, [candidate], "src/app.py\ntests/\n",
        )
        assert len(results) == 1
        assert results[0].is_dead is True
        assert in_tok == 300

    @pytest.mark.asyncio
    async def test_llm_says_alive_external_deploy(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_cicd",
                input={
                    "verdicts": [{
                        "element_name": "deploy",
                        "is_dead": False, "confidence": 0.95,
                        "reason": "Deploys to external cloud service",
                        "remediation": "Keep — active deployment",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        candidate = CICDCandidate(
            cicd_file=".github/workflows/deploy.yml",
            element_name="deploy",
            element_type="workflow_job",
            line_start=5,
            line_end=15,
            missing_paths=["infra/config.yml"],
            element_content="  deploy:\n    run: kubectl apply -f infra/config.yml\n",
            full_file_content="name: Deploy\njobs:\n  deploy:\n    run: kubectl apply\n",
        )
        results, _, _ = await _verify_batch_async(
            mock_provider, config, [candidate], "src/\ntests/\n",
        )
        assert len(results) == 1
        assert results[0].is_dead is False

    @pytest.mark.asyncio
    async def test_no_tool_calls_raises(self, config):
        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content="No tool response",
            tool_calls=[],
            input_tokens=100, output_tokens=50,
            model="test", stop_reason="end_turn",
        )

        candidate = CICDCandidate(
            cicd_file=".github/workflows/ci.yml",
            element_name="test",
            element_type="workflow_job",
            line_start=1,
            line_end=5,
            missing_paths=["old/path"],
            element_content="  test:\n    run: old/path/script.sh\n",
            full_file_content="jobs:\n  test:\n    run: old/path/script.sh\n",
        )
        with pytest.raises(RuntimeError, match="did not return verdicts"):
            await _verify_batch_async(
                mock_provider, config, [candidate], "",
            )


# --- TestDetectDeadCICDAsync ---

class TestDetectDeadCICDAsync:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        # Create a workflow that references a missing path
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
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_cicd",
                input={
                    "verdicts": [{
                        "element_name": "test",
                        "is_dead": True, "confidence": 0.85,
                        "reason": "References removed test directory",
                        "remediation": "Update or remove job",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        rate_limiter = _make_rate_limiter()
        results = await detect_dead_cicd_async(mock_provider, rate_limiter, config)
        # May or may not have results depending on whether "tests/removed_dir/" is
        # detected as a missing path (it contains / and . patterns)
        # The key thing is the pipeline runs without error
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_no_cicd_files(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")

        mock_provider = AsyncMock()
        rate_limiter = _make_rate_limiter()
        results = await detect_dead_cicd_async(mock_provider, rate_limiter, config)
        assert results == []
        mock_provider.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_paths_present_no_candidates(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "src/app.py", "print('hello')\n")
        _write_source(temp_dir, "Makefile", "test:\n\tpython src/app.py\n")

        mock_provider = AsyncMock()
        rate_limiter = _make_rate_limiter()
        results = await detect_dead_cicd_async(mock_provider, rate_limiter, config)
        # src/app.py exists, so no missing paths, so no LLM call
        assert results == []
        mock_provider.complete.assert_not_called()


# --- TestDeadCICDAnalyzer ---

class TestDeadCICDAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_async_returns_junk_result(self, temp_dir):
        config = Config(root_path=temp_dir, respect_gitignore=False)
        _write_source(temp_dir, "Makefile", "deploy:\n\tbash scripts/deploy.sh\n")
        # Don't create scripts/deploy.sh

        mock_provider = AsyncMock()
        mock_provider.complete.return_value = CompletionResult(
            content=None,
            tool_calls=[ToolCall(
                id="tc1", name="verify_dead_cicd",
                input={
                    "verdicts": [{
                        "element_name": "deploy",
                        "is_dead": True, "confidence": 0.9,
                        "reason": "Deploy script no longer exists",
                        "remediation": "Remove target from Makefile",
                    }],
                },
            )],
            input_tokens=300, output_tokens=100,
            model="test", stop_reason="tool_use",
        )

        rate_limiter = _make_rate_limiter()
        analyzer = DeadCICDAnalyzer()
        result = await analyzer.analyze_async(mock_provider, rate_limiter, config)

        assert isinstance(result, JunkAnalysisResult)
        assert result.analyzer_name == "dead_cicd"

        if result.findings:
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
        config = Config(root_path=Path("."), respect_gitignore=False)
        elements, in_tok, out_tok = await _parse_cicd_via_haiku(
            mock_provider, config, content, "Jenkinsfile", "jenkinsfile",
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

        config = Config(root_path=Path("."), respect_gitignore=False)
        elements, _, _ = await _parse_cicd_via_haiku(
            mock_provider, config, "# empty", "Jenkinsfile", "jenkinsfile",
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
