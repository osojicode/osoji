"""Shared pytest fixtures for osoji tests."""

import shutil
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

from osoji.walker import clear_repo_files_cache

# The CLI loads .env at its entry point (cli.py); pytest never goes through it,
# so the LLM-backed prompt_regression tests would only see keys exported by the
# shell. Load it here the same way — non-overriding, no-op when absent (CI).
load_dotenv()


def pytest_addoption(parser):
    parser.addoption(
        "--establish-baseline",
        action="store_true",
        default=False,
        help="Run prompt regression tests in baseline establishment mode",
    )
    parser.addoption(
        "--evaluate",
        action="store_true",
        default=False,
        help="Run the V1-7 corpus evaluator against the committed corpus (live LLM calls)",
    )
    parser.addoption(
        "--evaluate-out",
        action="store",
        default="tests/fixtures/prompt_regression/runs",
        help="Directory --evaluate writes its <run_id>.ndjson into",
    )


@pytest.fixture
def establish_baseline(request):
    return request.config.getoption("--establish-baseline")


@pytest.fixture
def evaluate_mode(request):
    return request.config.getoption("--evaluate")


@pytest.fixture
def evaluate_out(request):
    return Path(request.config.getoption("--evaluate-out"))


def pytest_collection_modifyitems(config, items):
    """When --evaluate is passed, run ONLY corpus_evaluate-marked tests.

    The ticketed invocation (``pytest tests/test_prompt_regression.py
    --evaluate``) must run just the corpus evaluator — the legacy statistical
    tests in that file each burn 10-68 live LLM trials and must not fire as a
    side effect of also being collected. Mirrors pytest's own ``-k``/``-m``
    deselect idiom (``config.hook.pytest_deselected`` + ``items[:] = ...``).
    Without --evaluate, collection is unchanged.
    """
    if not config.getoption("--evaluate"):
        return

    remaining = []
    deselected = []
    for item in items:
        if item.get_closest_marker("corpus_evaluate") is None:
            deselected.append(item)
        else:
            remaining.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining


@pytest.fixture(autouse=True)
def _clear_repo_files_cache():
    """Clear the git ls-files cache before and after each test."""
    clear_repo_files_cache()
    yield
    clear_repo_files_cache()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    dir_path = Path(tempfile.mkdtemp())
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


